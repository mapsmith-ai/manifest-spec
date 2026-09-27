using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using ArcGIS.Core.Events;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Core.Events;
using ArcGIS.Desktop.Core.Geoprocessing;

namespace ProvenanceManifest
{
    // With /provenance-manifest-autotest and a throwaway project on the command
    // line: runs a fixed sequence of tools through ExecuteToolAsync, waits for
    // every manifest, and exits the process (FrameworkApplication.Close and
    // ShutdownAsync do not close Pro from an add-in at startup: measured). The
    // caller checks the manifests; this only produces them.
    internal static class Autotest
    {
        public const string Switch = "/provenance-manifest-autotest";
        private static SubscriptionToken _open;
        private static int _started;

        public static void Arm(Emitter emitter)
        {
            Emitter.Log("autotest armed");
            _open = ProjectOpenedEvent.Subscribe(_ => Kick(emitter), true);
            if (Project.Current != null) Kick(emitter);
        }

        private static void Kick(Emitter emitter)
        {
            if (Interlocked.Exchange(ref _started, 1) == 1) return;
            _ = RunAsync(emitter);
        }

        private static async Task RunAsync(Emitter emitter)
        {
            try
            {
                await Task.Delay(2000);
                var gdb = Project.Current.DefaultGeodatabasePath;
                var env = Geoprocessing.MakeEnvironmentArray(overwriteoutput: true);
                var hist = GPExecuteToolFlags.AddToHistory;   // what the GUI does by default
                await Tool("management.CreateFishnet", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet"), "0 0", "0 10", 10, 10, 3, 3, "", "NO_LABELS", "", "POLYGON"), env,
                    hist | GPExecuteToolFlags.AddOutputsToMap);   // the layer the name test below uses
                await Tool("analysis.Buffer", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet"), Path.Combine(gdb, "at_buffer"), "1 Meters"), env, hist);
                // A layer name as input, as the Python window passes it.
                await Tool("analysis.Buffer", Geoprocessing.MakeValueArray(
                    "at_fishnet", Path.Combine(gdb, "at_buffer_from_layer"), "2 Meters"), env, hist);
                // Without history the start carries no parameters: hashed after the run.
                await Tool("management.CopyFeatures", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_buffer"), Path.Combine(gdb, "at_copy")), env, GPExecuteToolFlags.None);
                // In-place edits: the dataset is both input and (derived) output. Wait
                // for CopyFeatures' manifest first, so the edits find it to keep.
                await Tool("management.CopyFeatures", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet"), Path.Combine(gdb, "at_edit")), env, hist);
                await Task.WhenAll(emitter.AllFinished.ToArray());
                await Tool("management.AddField", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_edit"), "v", "LONG"), env, hist);
                await Task.WhenAll(emitter.AllFinished.ToArray());
                await Tool("management.CalculateField", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_edit"), "v", "1", "PYTHON3"), env, hist);
                await Task.Delay(1000);
                var all = emitter.AllFinished.ToArray();
                Emitter.Log($"autotest waiting for {all.Length} manifests");
                var done = await Task.WhenAny(Task.WhenAll(all), Task.Delay(120000));
                Emitter.Log(done is Task t && t.IsCompleted && all.All(x => x.IsCompleted)
                    ? "autotest: all manifests written" : "autotest: timed out waiting for manifests");
            }
            catch (Exception ex)
            {
                Emitter.Log("autotest-error " + ex);
            }
            finally
            {
                try { Project.Current?.SetDirty(false); } catch { }
                Emitter.Log("autotest exit");
                Environment.Exit(0);
            }
        }

        private static async Task Tool(string tool, System.Collections.Generic.IReadOnlyList<string> args,
            System.Collections.Generic.IEnumerable<System.Collections.Generic.KeyValuePair<string, string>> env, GPExecuteToolFlags flags)
        {
            var r = await Geoprocessing.ExecuteToolAsync(tool, args, env, null, null, flags);
            Emitter.Log($"autotest ran {tool} flags={flags} error={r.ErrorCode}");
        }
    }
}
