using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Core.Events;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace ProvenanceManifest
{
    // One geoprocessing run, from the start event to the manifest.
    internal sealed class Run
    {
        public string StartId;
        public string Tool;
        public string CapturePath;
        public JsonObject Capture;
        public Task Started;          // capture written + `capture start` finished
        public Task Finished;         // manifest written
    }

    // Measured on ArcGIS Pro 3.7.1 (2026-09-27, probe and autotest):
    // - GPExecuteToolEvent fires for the Geoprocessing pane, the Python window
    //   and ExecuteToolAsync; not for a model run from ModelBuilder, and a model
    //   run from code gives one event for the model and none for its tools.
    // - With the run going to the project history (the default in the GUI) the
    //   start event carries every parameter; without it, the start carries none
    //   and the end carries them all.
    // - The event never blocks the tool, so digests taken at start run
    //   concurrently with it.
    // - Start and end IDs match for the pane and for code, not for the Python
    //   window; the tool name (Path) is null for the pane.
    internal sealed class Emitter
    {
        private static readonly string Root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ProvenanceManifest");
        private static readonly string Captures = Path.Combine(Root, "captures");
        private static readonly string PythonDir = Path.Combine(Root, "python");
        private static readonly string LogPath = Path.Combine(Root, "addin.log");
        // The Python that ships with this ArcGIS Pro, found from the running
        // executable rather than assumed at the default install location.
        private static readonly string ProPython = Path.Combine(
            Path.GetDirectoryName(Process.GetCurrentProcess().MainModule?.FileName ?? @"C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.exe"),
            "Python", "envs", "arcgispro-py3", "python.exe");

        private static readonly HashSet<string> LayerTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "GPFeatureLayer", "GPRasterLayer", "GPTableView", "GPLayer", "GPMosaicLayer", "GPCompositeLayer",
            "GPFeatureRecordSetLayer", "GPRasterDataLayer", "GPLasDatasetLayer", "GPTinLayer",
        };

        private readonly ConcurrentDictionary<string, Run> _byId = new ConcurrentDictionary<string, Run>();
        private readonly ConcurrentQueue<Run> _order = new ConcurrentQueue<Run>();
        public readonly ConcurrentBag<Task> AllFinished = new ConcurrentBag<Task>();

        public Emitter()
        {
            Directory.CreateDirectory(Captures);
            ExtractPython();
            Log("loaded; python package in " + PythonDir);
        }

        private static void ExtractPython()
        {
            var target = Path.Combine(PythonDir, "provenance_manifest_arcgis_pro");
            Directory.CreateDirectory(target);
            var asm = Assembly.GetExecutingAssembly();
            foreach (var name in asm.GetManifestResourceNames().Where(n => n.StartsWith("python/")))
            {
                using var s = asm.GetManifestResourceStream(name);
                using var f = File.Create(Path.Combine(target, name.Substring("python/".Length)));
                s.CopyTo(f);
            }
        }

        public void OnToolEvent(GPExecuteToolEventArgs e)
        {
            try
            {
                if (e.IsStarting) OnStart(e);
                else OnEnd(e);
            }
            catch (Exception ex)
            {
                Log("event-error " + ex);
            }
        }

        private static string Launch(string id) =>
            id == null ? "unknown"
            : id.StartsWith("Background") ? "geoprocessing_pane"
            : id.StartsWith("Python") ? "python_window"
            : id.StartsWith("Foreground") ? "code"
            : "unknown";

        private void OnStart(GPExecuteToolEventArgs e)
        {
            var parameters = Params(e.GPResult);
            var run = new Run { StartId = e.ID, Tool = e.Path };
            var id = Guid.NewGuid().ToString("N");
            run.CapturePath = Path.Combine(Captures, id + ".capture.json");
            run.Capture = new JsonObject
            {
                ["capture_version"] = 1,
                ["tool"] = e.Path,
                ["run_id"] = id,
                ["launch"] = Launch(e.ID),
                ["started_at"] = Now(),
                ["inputs_hashed"] = parameters.Count > 0 ? "at_start" : "after_run",
                ["parameters"] = new JsonArray(),
            };
            _byId[e.ID ?? id] = run;
            _order.Enqueue(run);
            run.Started = Task.Run(async () =>
            {
                if (parameters.Count == 0) return;   // nothing to hash yet: hashed after the run
                run.Capture["parameters"] = await Resolve(parameters);
                Save(run);
                await Python("start", run.CapturePath);
            });
        }

        private void OnEnd(GPExecuteToolEventArgs e)
        {
            var run = Match(e);
            if (run == null)
            {
                Log($"end without a start: id={e.ID} path={e.Path}");
                return;
            }
            var r = e.GPResult;
            var endParams = Params(r);
            run.Finished = Task.Run(async () =>
            {
                try
                {
                    await run.Started;
                    if (File.Exists(run.CapturePath))
                        run.Capture = JsonNode.Parse(File.ReadAllText(run.CapturePath, Encoding.UTF8)).AsObject();
                    // The end carries the values the tool ran with (defaults filled);
                    // the paths are resolved again because outputs only exist now.
                    run.Capture["parameters"] = await Resolve(endParams);
                    run.Capture["finished_at"] = Now();
                    run.Capture["succeeded"] = r != null && !r.IsFailed && r.ErrorCode == 0;
                    run.Capture["error_code"] = r?.ErrorCode ?? -1;
                    run.Capture["messages"] = new JsonArray((r?.Messages ?? Enumerable.Empty<IGPMessage>())
                        .Select(m => (JsonNode)JsonValue.Create(m.Text)).ToArray());
                    var env = new JsonObject();
                    foreach (var x in r?.Environments ?? Enumerable.Empty<Tuple<string, string, string>>())
                        env[x.Item1] = x.Item3;
                    run.Capture["environments"] = env;
                    if (string.IsNullOrEmpty(run.Tool) && !string.IsNullOrEmpty(e.Path)) run.Capture["tool"] = e.Path;
                    if (run.Capture["tool"] == null || string.IsNullOrEmpty((string)run.Capture["tool"]))
                        run.Capture["tool"] = await ToolFromHistory(endParams);
                    Save(run);
                    if ((string)run.Capture["inputs_hashed"] == "after_run")
                        await Python("start", run.CapturePath);
                    await Python("finish", run.CapturePath);
                }
                catch (Exception ex)
                {
                    Log("finish-error " + ex);
                }
            });
            AllFinished.Add(run.Finished);
        }

        // Start and end IDs match for the pane and for code; for the Python window
        // they do not, so fall back to the oldest pending run of the same tool.
        private Run Match(GPExecuteToolEventArgs e)
        {
            if (e.ID != null && _byId.TryRemove(e.ID, out var byId)) return byId;
            var pending = _order.Where(r => r.Finished == null).ToList();
            var candidate = pending.FirstOrDefault(r => r.Tool == e.Path) ?? pending.FirstOrDefault();
            if (candidate != null)
                foreach (var kv in _byId.Where(kv => kv.Value == candidate).ToList()) _byId.TryRemove(kv.Key, out _);
            return candidate;
        }

        private static List<(string name, string type, string value, bool isInput)> Params(IGPResult r) =>
            (r?.Parameters ?? Enumerable.Empty<Tuple<string, string, string, bool>>())
            .Select(p => (p.Item1, p.Item2, p.Item3, p.Item4)).ToList();

        // Each parameter, and the datasets on disk it refers to: every value of a
        // multi-value parameter (Merge's inputs arrive as "a;b"), each a path as
        // given or the source of the layer a name refers to (the Python window
        // passes layer names). A value that names a dataset and resolves to no
        // file is listed in `unresolved`, so the record can say so instead of
        // dropping it. For a layer, its selection and definition query are kept:
        // a tool reads only the selected features, while the digest covers the
        // whole dataset.
        private static async Task<JsonArray> Resolve(List<(string name, string type, string value, bool isInput)> ps)
        {
            var arr = new JsonArray();
            foreach (var p in ps)
            {
                bool datasetType = p.type != null && (p.type.StartsWith("DE") || LayerTypes.Contains(p.type)
                    || p.type.StartsWith("GPMultiValue", StringComparison.OrdinalIgnoreCase));
                var paths = new JsonArray();
                var unresolved = new JsonArray();
                var filters = new JsonArray();
                if (datasetType)
                {
                    foreach (var raw in (p.value ?? "").Split(';'))
                    {
                        var value = raw.Trim().Trim('\'', '"');
                        if (value.Length == 0) continue;
                        if (Path.IsPathRooted(value)) { paths.Add(value); continue; }
                        var source = await LayerSource(value);
                        if (source.path != null)
                        {
                            paths.Add(source.path);
                            if (source.selection > 0 || !string.IsNullOrEmpty(source.definitionQuery))
                                filters.Add(new JsonObject
                                {
                                    ["layer"] = value, ["selection_count"] = source.selection,
                                    ["definition_query"] = source.definitionQuery,
                                });
                        }
                        else unresolved.Add(value);
                    }
                }
                arr.Add(new JsonObject
                {
                    ["name"] = p.name, ["type"] = p.type, ["value"] = p.value, ["is_input"] = p.isInput,
                    ["dataset"] = datasetType,
                    ["path"] = paths.Count == 1 ? paths[0]?.GetValue<string>() : null,
                    ["paths"] = paths, ["unresolved"] = unresolved, ["layer_filters"] = filters,
                });
            }
            return arr;
        }

        private static Task<(string path, long selection, string definitionQuery)> LayerSource(string name) => QueuedTask.Run(() =>
        {
            var maps = new List<Map>();
            if (MapView.Active?.Map != null) maps.Add(MapView.Active.Map);
            if (Project.Current != null)
                maps.AddRange(Project.Current.GetItems<MapProjectItem>().Select(i => i.GetMap()).Where(m => m != null && !maps.Contains(m)));
            foreach (var map in maps)
            {
                var layer = map.FindLayers(name, true).FirstOrDefault();
                var uri = layer?.GetPath();
                if (uri == null || !uri.IsFile) continue;
                long selection = 0;
                string query = null;
                if (layer is BasicFeatureLayer fl)
                {
                    selection = fl.SelectionCount;
                    query = fl.DefinitionQuery;
                }
                return (uri.LocalPath, selection, query);
            }
            return ((string)null, 0L, (string)null);
        });

        // The pane gives no tool name: the most recent history entry whose output
        // values match this run's supplies it.
        private static Task<string> ToolFromHistory(List<(string name, string type, string value, bool isInput)> ps) => QueuedTask.Run(() =>
        {
            var items = Project.Current?.GetProjectItemContainer(Geoprocessing.HistoryContainerKey) as IEnumerable<IGPHistoryItem>;
            if (items == null) return (string)null;
            var outputs = ps.Where(p => !p.isInput).Select(p => p.value).ToHashSet();
            var hit = items.OrderByDescending(h => h.TimeStamp)
                .FirstOrDefault(h => h.GPResult?.Parameters?.Where(p => !p.Item4).Select(p => p.Item3).ToHashSet().SetEquals(outputs) == true);
            return hit?.ToolPath;
        });

        public static void OnProjectItemsChanged(ProjectItemsChangedEventArgs e)
        {
            try
            {
                var items = e.ProjectItemsCollection ?? (e.ProjectItem != null ? new List<Item> { e.ProjectItem } : new List<Item>());
                foreach (var h in items.OfType<IGPHistoryItem>())
                {
                    var outs = h.GPResult?.Parameters?.Where(p => !p.Item4).Select(p => p.Item3).ToArray() ?? Array.Empty<string>();
                    Log($"history-item action={e.Action} tool={h.ToolPath} time={h.TimeStamp:o} outputs={string.Join(" | ", outs)}");
                }
            }
            catch (Exception ex)
            {
                Log("history-error " + ex.Message);
            }
        }

        private static void Save(Run run)
        {
            var tmp = run.CapturePath + ".tmp";
            File.WriteAllText(tmp, run.Capture.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
            File.Move(tmp, run.CapturePath, true);
        }

        private static async Task Python(string step, string capture)
        {
            var psi = new ProcessStartInfo(ProPython)
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            psi.ArgumentList.Add("-m");
            psi.ArgumentList.Add("provenance_manifest_arcgis_pro.capture");
            psi.ArgumentList.Add(step);
            psi.ArgumentList.Add(capture);
            // Pro's own process carries PYTHONPATH and PYTHONIOENCODING (measured):
            // the child must not inherit Pro's PYTHONPATH, only find our package.
            psi.Environment.Remove("PYTHONHOME");
            psi.Environment["PYTHONPATH"] = PythonDir;
            psi.Environment["PYTHONUTF8"] = "1";
            using var p = Process.Start(psi);
            var stdout = p.StandardOutput.ReadToEndAsync();
            var stderr = p.StandardError.ReadToEndAsync();
            await p.WaitForExitAsync();
            Log($"python {step} exit={p.ExitCode} {Path.GetFileName(capture)} {(await stdout).Trim()} {(await stderr).Trim()}");
        }

        private static string Now() => DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");

        private static readonly object Gate = new object();

        public static void Log(string line)
        {
            lock (Gate)
            {
                Directory.CreateDirectory(Root);
                File.AppendAllText(LogPath, DateTime.UtcNow.ToString("o") + " " + line + Environment.NewLine);
            }
        }
    }
}
