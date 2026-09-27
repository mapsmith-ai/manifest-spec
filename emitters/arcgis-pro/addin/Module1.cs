using System;
using System.IO;
using System.Linq;
using ArcGIS.Core.Events;
using ArcGIS.Desktop.Core.Events;
using ArcGIS.Desktop.Framework.Contracts;

namespace ProvenanceManifest
{
    // Loads with ArcGIS Pro and listens to every geoprocessing run -- but only
    // when asked to. Writing a file beside every output of every session is not
    // something an add-in should start doing because it was installed, so it is
    // inert unless one of these holds: Pro was started with /provenance-manifest
    // or with the autotest switch, or the user created the opt-in file
    // %LOCALAPPDATA%\ProvenanceManifest\enabled.
    internal class Module1 : Module
    {
        public const string EnableSwitch = "/provenance-manifest";
        private SubscriptionToken _gpToken, _historyToken;
        private Emitter _emitter;

        protected override bool Initialize()
        {
            try
            {
                var args = Environment.GetCommandLineArgs();
                bool autotest = args.Any(a => a.Equals(Autotest.Switch, StringComparison.OrdinalIgnoreCase));
                bool enabled = autotest
                    || args.Any(a => a.Equals(EnableSwitch, StringComparison.OrdinalIgnoreCase))
                    || File.Exists(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "ProvenanceManifest", "enabled"));
                if (!enabled) return true;
                _emitter = new Emitter();
                _gpToken = GPExecuteToolEvent.Subscribe(_emitter.OnToolEvent, true);
                // Measurement for ModelBuilder, which raises no tool event: does a
                // model run add to the project history? Logged, not yet acted on.
                _historyToken = ProjectItemsChangedEvent.Subscribe(Emitter.OnProjectItemsChanged, true);
                if (autotest) Autotest.Arm(_emitter);
            }
            catch (Exception ex)
            {
                Emitter.Log("initialize-error " + ex);
            }
            return true;
        }

        protected override void Uninitialize()
        {
            if (_gpToken != null) GPExecuteToolEvent.Unsubscribe(_gpToken);
            if (_historyToken != null) ProjectItemsChangedEvent.Unsubscribe(_historyToken);
        }

        protected override bool CanUnload() => true;
    }
}
