// Inspect and normalize only our freshly compiled helper. Never execute game code.
using System;
using System.IO;
using System.Linq;
using Mono.Cecil;

class Prepare
{
    static int Main(string[] args)
    {
        try
        {
            if (args.Length != 2 || Path.GetFileName(args[0]) != "BongoCatChat.MergeBridge.Live.dll") return 2;
            using (var resolver = new DefaultAssemblyResolver())
            {
                resolver.AddSearchDirectory(args[1]);
                var options = new ReaderParameters { AssemblyResolver = resolver, ReadWrite = true };
                using (var assembly = AssemblyDefinition.ReadAssembly(args[0], options))
                {
                    if (assembly.Name.Name != "BongoCatChat.MergeBridge.Live") return 3;
                    foreach (var attribute in assembly.CustomAttributes.Where(a => a.AttributeType.FullName == "System.Runtime.CompilerServices.CompilationRelaxationsAttribute").ToArray())
                        assembly.CustomAttributes.Remove(attribute);
                    assembly.Write();
                }
                // Reopen after rewriting: GetMemberReferences otherwise includes
                // the removed attribute's stale metadata reference.
                options.ReadWrite = false;
                using (var assembly = AssemblyDefinition.ReadAssembly(args[0], options))
                {
                    foreach (var member in assembly.MainModule.GetMemberReferences())
                    {
                        var method = member as MethodReference;
                        var field = member as FieldReference;
                        if (method != null && method.Resolve() == null || field != null && field.Resolve() == null) return 4;
                    }
                }
            }
            return 0;
        }
        catch { return 1; }
    }
}
