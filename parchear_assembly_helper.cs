using System;
using System.Collections.Generic;
using System.IO;
using Mono.Cecil;
using Mono.Cecil.Cil;

internal static class AssemblyPatcher
{
    private sealed class Replacement
    {
        internal readonly string Source;
        internal readonly string Target;
        internal readonly int ExpectedCount;
        internal int ActualCount;

        internal Replacement(string source, string target, int expectedCount)
        {
            Source = source;
            Target = target;
            ExpectedCount = expectedCount;
        }
    }

    private static readonly List<Replacement> Replacements = new List<Replacement>
    {
        new Replacement(" and ", " y ", 6),
        new Replacement(" or ", " o ", 5),
        new Replacement(" was ", " era ", 2),
        new Replacement("and", " y ", 7),
        new Replacement("was", "era", 2),
        new Replacement("wasn't", "no era", 2),
        new Replacement("were", "eran", 4),
        new Replacement("weren't", "no eran", 2),
        new Replacement(
            "You stated that you are the real {0}, and that {1} are fakes.",
            "Afirmaste que eras el auténtico {0}, y que {1} eran impostores.",
            1
        ),
    };

    private static IEnumerable<TypeDefinition> WalkTypes(IEnumerable<TypeDefinition> roots)
    {
        foreach (TypeDefinition type in roots)
        {
            yield return type;
            foreach (TypeDefinition nested in WalkTypes(type.NestedTypes))
            {
                yield return nested;
            }
        }
    }

    private static int Main(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("usage: AssemblyPatcher INPUT_DLL OUTPUT_DLL");
            return 2;
        }

        string inputPath = Path.GetFullPath(args[0]);
        string outputPath = Path.GetFullPath(args[1]);
        if (String.Equals(inputPath, outputPath, StringComparison.Ordinal))
        {
            Console.Error.WriteLine("refusing to patch a DLL in place");
            return 2;
        }

        using (AssemblyDefinition assembly = AssemblyDefinition.ReadAssembly(
            inputPath,
            new ReaderParameters { InMemory = true, ReadSymbols = false }
        ))
        {
            if (assembly.Name.Name != "Assembly-CSharp")
            {
                Console.Error.WriteLine("input is not Assembly-CSharp.dll");
                return 2;
            }

            foreach (TypeDefinition type in WalkTypes(assembly.MainModule.Types))
            {
                foreach (MethodDefinition method in type.Methods)
                {
                    if (!method.HasBody)
                    {
                        continue;
                    }

                    foreach (Instruction instruction in method.Body.Instructions)
                    {
                        if (instruction.OpCode != OpCodes.Ldstr)
                        {
                            continue;
                        }

                        string operand = instruction.Operand as string;
                        foreach (Replacement replacement in Replacements)
                        {
                            if (operand == replacement.Source)
                            {
                                instruction.Operand = replacement.Target;
                                replacement.ActualCount++;
                                break;
                            }
                        }
                    }
                }
            }

            bool countsMatch = true;
            foreach (Replacement replacement in Replacements)
            {
                Console.WriteLine(
                    "{0} -> {1}: {2}/{3}",
                    Escape(replacement.Source),
                    Escape(replacement.Target),
                    replacement.ActualCount,
                    replacement.ExpectedCount
                );
                if (replacement.ActualCount != replacement.ExpectedCount)
                {
                    countsMatch = false;
                }
            }
            if (!countsMatch)
            {
                Console.Error.WriteLine("unexpected IL match counts; output was not written");
                return 1;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            assembly.Write(outputPath, new WriterParameters { WriteSymbols = false });
        }

        return 0;
    }

    private static string Escape(string value)
    {
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
