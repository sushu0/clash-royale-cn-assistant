using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Resources;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

if (args.Length != 4) throw new ArgumentException("Usage: PackageVerifier APP_DIRECTORY SOURCE_PROJECT_DIRECTORY EVIDENCE_DIRECTORY BUILD_ROOT_DIRECTORY");
string app = Path.GetFullPath(args[0]);
string source = Path.GetFullPath(args[1]);
string evidence = Path.GetFullPath(args[2]);
string buildRoot = Path.GetFullPath(args[3]);
foreach (string path in new[]{app,source,evidence,buildRoot})
    if (!path.StartsWith(@"D:\codex\",StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Paths must stay under D:\\codex.");
string exe = Path.Combine(app,"ClashAssistant.Desktop.exe");
string dll = Path.Combine(app,"ClashAssistant.Desktop.dll");
string pdb = Path.Combine(app,"ClashAssistant.Desktop.pdb");
using var peStream = File.OpenRead(dll);
using var pe = new PEReader(peStream);
var assembly = pe.GetMetadataReader();
string configuration = "";
foreach(var handle in assembly.GetAssemblyDefinition().GetCustomAttributes())
{
    var attribute = assembly.GetCustomAttribute(handle);
    if(attribute.Constructor.Kind != HandleKind.MemberReference) continue;
    var member = assembly.GetMemberReference((MemberReferenceHandle)attribute.Constructor);
    if(member.Parent.Kind != HandleKind.TypeReference) continue;
    var type = assembly.GetTypeReference((TypeReferenceHandle)member.Parent);
    if(assembly.GetString(type.Name) != "AssemblyConfigurationAttribute") continue;
    var value = assembly.GetBlobReader(attribute.Value);
    if(value.ReadUInt16() == 1) configuration = value.ReadSerializedString() ?? "";
}
if(configuration != "Release") throw new InvalidDataException("The published assembly is not the Release build: " + configuration);
using var pdbStream = File.OpenRead(pdb);
using var provider = MetadataReaderProvider.FromPortablePdbStream(pdbStream);
var symbols = provider.GetMetadataReader();
var documents = new Dictionary<string,object>(StringComparer.OrdinalIgnoreCase);
foreach(var handle in symbols.Documents)
{
    var document = symbols.GetDocument(handle);
    string path = symbols.GetString(document.Name);
    byte[] expected = symbols.GetBlobBytes(document.Hash);
    if(!File.Exists(path) || expected.Length == 0) continue;
    byte[] content = File.ReadAllBytes(path);
    byte[] actual = expected.Length == 32 ? SHA256.HashData(content) : SHA1.HashData(content);
    bool matches = actual.AsSpan().SequenceEqual(expected);
    documents[Path.GetFullPath(path)] = new { Path=path,Checksum=Convert.ToHexString(expected),HashBytes=expected.Length,Matches=matches };
    if(!matches) throw new InvalidDataException("PDB source checksum differs from the saved source: " + path);
}
var sourceFiles = Directory.EnumerateFiles(source,"*.cs",SearchOption.AllDirectories)
    .Where(path=>!path.Contains(@"\obj\",StringComparison.OrdinalIgnoreCase)&&!path.Contains(@"\bin\",StringComparison.OrdinalIgnoreCase)).ToArray();
foreach(string path in sourceFiles)
    if(!documents.ContainsKey(Path.GetFullPath(path))) throw new InvalidDataException("Saved C# source is absent from published PDB: " + path);
var codeViewEntry = pe.ReadDebugDirectory().First(item=>item.Type == DebugDirectoryEntryType.CodeView);
var codeView = pe.ReadCodeViewDebugDirectoryData(codeViewEntry);
var pdbId = symbols.DebugMetadataHeader!.Id;
if(new Guid(pdbId.AsSpan(0,16)) != codeView.Guid) throw new InvalidDataException("Published DLL and portable PDB identities differ.");
using var exeStream = File.OpenRead(exe);
using var exePe = new PEReader(exeStream);
bool gui = exePe.PEHeaders.PEHeader!.Subsystem == Subsystem.WindowsGui;
if(!gui) throw new InvalidDataException("Published executable uses a console subsystem.");
string before = Path.Combine(evidence,"old-reports-before.json");
using var baseline = JsonDocument.Parse(File.ReadAllText(before));
var reportChecks = baseline.RootElement.GetProperty("Files").EnumerateArray().Select(item=>
{
    string path=item.GetProperty("Path").GetString()!;
    string digest=item.GetProperty("Sha256").GetString()!;
    bool matches=File.Exists(path)&&Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).Equals(digest,StringComparison.OrdinalIgnoreCase);
    if(!matches) throw new InvalidDataException("Existing report changed or disappeared: " + path);
    return new{Path=path,Preserved=matches,Sha256=digest};
}).ToArray();
string debug = Path.Combine(buildRoot,"bin/Debug/net10.0-windows/ClashAssistant.Desktop.dll");
string releaseHash=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(dll)));
string? debugHash=File.Exists(debug)?Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(debug))):null;
var bamlResources=new Dictionary<string,byte[]>(StringComparer.OrdinalIgnoreCase);
foreach(var handle in assembly.ManifestResources)
{
    var resource=assembly.GetManifestResource(handle);
    if(!resource.Implementation.IsNil || !assembly.GetString(resource.Name).EndsWith(".g.resources",StringComparison.Ordinal)) continue;
    var section=pe.GetSectionData(pe.PEHeaders.CorHeader!.ResourcesDirectory.RelativeVirtualAddress).GetContent();
    int offset=checked((int)resource.Offset);
    int length=BitConverter.ToInt32(section.AsSpan(offset,4));
    using var resourceStream=new MemoryStream(section.AsSpan(offset+4,length).ToArray());
    using var resourceReader=new ResourceReader(resourceStream);
    var iterator=resourceReader.GetEnumerator();
    while(iterator.MoveNext())
    {
        string name=(string)iterator.Key;
        if(!name.EndsWith(".baml",StringComparison.OrdinalIgnoreCase)) continue;
        resourceReader.GetResourceData(name,out string resourceType,out byte[] raw);
        if(resourceType != "ResourceTypeCode.Stream" || raw.Length<4 || BitConverter.ToInt32(raw,0)!=raw.Length-4)
            throw new InvalidDataException("Unexpected BAML stream resource representation: " + name);
        bamlResources[name]=raw.AsSpan(4).ToArray();
    }
}
var xamlChecks=new List<object>();
foreach(string name in new[]{"App","MainWindow"})
{
    string xamlPath=Path.Combine(source,name+".xaml");
    string generated=Path.Combine(buildRoot,"obj/Release/net10.0-windows/win-x64",name+".g.cs");
    string bamlPath=Path.Combine(buildRoot,"obj/Release/net10.0-windows/win-x64",name+".baml");
    string generatedText=File.ReadAllText(generated);
    var checksum=Regex.Match(generatedText,"#pragma checksum \\\"[^\\\"]+\\\" \\\"(?<algorithm>[^\\\"]+)\\\" \\\"(?<checksum>[0-9A-Fa-f]+)\\\"");
    string sha1=Convert.ToHexString(SHA1.HashData(File.ReadAllBytes(xamlPath)));
    if(!checksum.Success || !checksum.Groups["checksum"].Value.Equals(sha1,StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("Current RID generated C# pragma does not match original XAML: " + xamlPath);
    string resourceName=name.ToLowerInvariant()+".baml";
    if(!bamlResources.TryGetValue(resourceName,out var compiledBaml)) throw new InvalidDataException("Published BAML resource missing: " + resourceName);
    if(!compiledBaml.AsSpan().SequenceEqual(File.ReadAllBytes(bamlPath))) throw new InvalidDataException("Published BAML differs from current RID build: " + resourceName);
    xamlChecks.Add(new{Source=xamlPath,SourceSha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(xamlPath))),
        SourceSha1=sha1,GeneratedSource=generated,GeneratedSourceSha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(generated))),
        PragmaAlgorithm=checksum.Groups["algorithm"].Value,PragmaOriginalXamlMatches=true,GeneratedSourceDocumentInPdb=documents.ContainsKey(generated),
        PublishedBamlResource=resourceName,BamlSha256=Convert.ToHexString(SHA256.HashData(compiledBaml)),BamlMatchesRidBuild=true,
        OriginalXamlDocumentInPdb=documents.ContainsKey(xamlPath)});
}
var result=new{
    VerifiedAt=DateTimeOffset.UtcNow,AppDirectory=app,Executable=exe,ExecutableSha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(exe))),
    Assembly=dll,AssemblySha256=releaseHash,AssemblyConfiguration=configuration,GuiSubsystem=gui,
    PortablePdb=pdb,PortablePdbSha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(pdb))),PortablePdbMatchesAssembly=true,
    SourceFileCount=sourceFiles.Length,SourceDocuments=documents.Values,AllSavedCSharpSourcesMatchPdb=true,
    PriorReports=reportChecks,PriorReportsPreserved=true,DebugAssembly=File.Exists(debug)?debug:null,DebugAssemblySha256=debugHash,
    ReleaseIsDistinctFromDebug=debugHash is null || debugHash != releaseHash,
    XamlSourceAndCompiledResourceChecks=xamlChecks,AllOriginalXamlPragmasAndPublishedBamlMatch=true,
    RuntimeConfiguration=JsonDocument.Parse(File.ReadAllText(Path.Combine(app,"ClashAssistant.Desktop.runtimeconfig.json"))).RootElement.Clone()
};
File.WriteAllText(Path.Combine(evidence,"wpf-package-source-manifest.json"),JsonSerializer.Serialize(result,new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine($"Release verified: {sourceFiles.Length} C# files match PDB, 2 XAML pragmas and BAML resources match, GUI subsystem, {reportChecks.Length} prior report files preserved.");

