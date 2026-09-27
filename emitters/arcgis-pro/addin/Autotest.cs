using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using ArcGIS.Core.CIM;
using ArcGIS.Core.Events;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Core.Events;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

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
                await OpenMapView();
                var gdb = Project.Current.DefaultGeodatabasePath;
                var env = Geoprocessing.MakeEnvironmentArray(overwriteoutput: true);
                var hist = GPExecuteToolFlags.AddToHistory;   // what the GUI does by default
                await Tool("management.CreateFishnet", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet"), "0 0", "0 10", 10, 10, 3, 3, "", "NO_LABELS", "", "POLYGON"), env,
                    hist | GPExecuteToolFlags.AddOutputsToMap);   // the layer the name test below uses
                await Tool("analysis.Buffer", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet"), Path.Combine(gdb, "at_buffer"), "1 Meters"), env, hist);
                // A layer name as input, as the Python window passes it. The layer
                // must exist only in the map: a bare "at_fishnet" is resolved by
                // ArcGIS to the feature class in the workspace (measured), which
                // would never exercise the add-in's layer resolution.
                await Tool("management.MakeFeatureLayer", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet"), "fishnet_view"), env,
                    hist | GPExecuteToolFlags.AddOutputsToMap);
                await Tool("analysis.Buffer", Geoprocessing.MakeValueArray(
                    "fishnet_view", Path.Combine(gdb, "at_buffer_from_layer"), "2 Meters"), env, hist);
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
                // Several inputs in one parameter, as Merge takes them.
                await Tool("management.Merge", Geoprocessing.MakeValueArray(
                    Path.Combine(gdb, "at_fishnet") + ";" + Path.Combine(gdb, "at_buffer"),
                    Path.Combine(gdb, "at_merge")), env, hist);
                // A selection on a layer: the tool reads 3 of 9 features while the
                // digest covers the dataset. The selection tool itself writes no
                // dataset and must leave the record of at_fishnet untouched.
                await Task.WhenAll(emitter.AllFinished.ToArray());
                await Tool("management.SelectLayerByAttribute", Geoprocessing.MakeValueArray(
                    "fishnet_view", "NEW_SELECTION", "OID <= 3"), env, hist);
                await Tool("analysis.Buffer", Geoprocessing.MakeValueArray(
                    "fishnet_view", Path.Combine(gdb, "at_buffer_selected"), "3 Meters"), env, hist);
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

        // A project opened from the command line shows no map view, and without an
        // active view AddOutputsToMap adds nothing: the layer made by
        // MakeFeatureLayer lived only in the geoprocessing session, which dropped
        // it a few tools later, and no map held it for the add-in to resolve
        // (measured: inputs [] on the first layer run, error on the later ones).
        // A person using the GUI always has a view open; the test opens one.
        private static async Task OpenMapView()
        {
            var item = Project.Current.GetItems<MapProjectItem>().FirstOrDefault();
            var map = item != null
                ? await QueuedTask.Run(() => item.GetMap())
                : await QueuedTask.Run(() => MapFactory.Instance.CreateMap("autotest", MapType.Map, MapViewingMode.Map, Basemap.None));
            await FrameworkApplication.Current.Dispatcher.InvokeAsync(() => FrameworkApplication.Panes.CreateMapPaneAsync(map)).Task.Unwrap();
            for (var i = 0; i < 60 && MapView.Active == null; i++) await Task.Delay(500);
            Emitter.Log(MapView.Active != null ? $"autotest map view open: {MapView.Active.Map.Name}" : "autotest: no map view after 30 s");
        }

        private static async Task Tool(string tool, System.Collections.Generic.IReadOnlyList<string> args,
            System.Collections.Generic.IEnumerable<System.Collections.Generic.KeyValuePair<string, string>> env, GPExecuteToolFlags flags)
        {
            var r = await Geoprocessing.ExecuteToolAsync(tool, args, env, null, null, flags);
            Emitter.Log($"autotest ran {tool} flags={flags} error={r.ErrorCode}");
        }
    }
}
