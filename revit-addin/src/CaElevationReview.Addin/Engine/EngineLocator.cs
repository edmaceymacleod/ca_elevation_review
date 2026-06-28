using System;
using System.Collections.Generic;
using System.IO;

namespace CaElevationReview.Addin.Engine
{
    /// <summary>
    /// A resolved way to invoke the engine: an executable plus any prefix args.
    /// e.g. ("ca-elevation", []) for the console script, or
    /// ("C:\\venv\\Scripts\\python.exe", ["-m", "ca_elevation_engine.cli"]) for a venv.
    /// </summary>
    public sealed class EngineCommand
    {
        public EngineCommand(string executable, IReadOnlyList<string>? prefixArgs = null)
        {
            Executable = executable;
            PrefixArgs = prefixArgs ?? Array.Empty<string>();
        }

        public string Executable { get; }
        public IReadOnlyList<string> PrefixArgs { get; }
    }

    /// <summary>
    /// Locates the <c>ca-elevation</c> CLI. Resolution order (first hit wins):
    ///   1. An explicit path passed to the constructor (from add-in settings).
    ///   2. The CA_ELEVATION_CLI environment variable.
    ///   3. A venv bundled next to the add-in DLL (./engine-venv/Scripts/...).
    ///   4. The bare "ca-elevation" console script on PATH.
    /// Pure logic apart from file-existence probing, which is injectable for tests.
    /// </summary>
    public sealed class EngineLocator
    {
        public const string EnvVarName = "CA_ELEVATION_CLI";
        private const string ConsoleScript = "ca-elevation";

        private readonly string? _explicitPath;
        private readonly Func<string, bool> _fileExists;
        private readonly Func<string, string?> _envReader;
        private readonly string _addinDir;

        /// <param name="explicitPath">Configured CLI path from add-in settings, or null.</param>
        /// <param name="addinDir">Directory containing the add-in DLL (for bundled-venv probing).</param>
        /// <param name="fileExists">File-existence probe; injectable for unit tests.</param>
        /// <param name="envReader">Environment reader; injectable for unit tests.</param>
        public EngineLocator(
            string? explicitPath = null,
            string? addinDir = null,
            Func<string, bool>? fileExists = null,
            Func<string, string?>? envReader = null)
        {
            _explicitPath = string.IsNullOrWhiteSpace(explicitPath) ? null : explicitPath;
            _addinDir = addinDir ?? AppContext.BaseDirectory ?? Directory.GetCurrentDirectory();
            _fileExists = fileExists ?? File.Exists;
            _envReader = envReader ?? Environment.GetEnvironmentVariable;
        }

        /// <summary>
        /// Resolve a runnable command, or throw <see cref="EngineNotFoundException"/> if
        /// nothing concrete is found (the PATH fallback is returned without probing, so
        /// resolution only throws when an explicit/env path is given but missing).
        /// </summary>
        public EngineCommand Resolve()
        {
            // 1. Explicit configured path.
            if (_explicitPath != null)
            {
                if (_fileExists(_explicitPath)) return Wrap(_explicitPath);
                throw new EngineNotFoundException(
                    $"Configured engine path does not exist: {_explicitPath}");
            }

            // 2. Environment variable.
            string? fromEnv = _envReader(EnvVarName);
            if (!string.IsNullOrWhiteSpace(fromEnv))
            {
                if (_fileExists(fromEnv!)) return Wrap(fromEnv!);
                throw new EngineNotFoundException(
                    $"{EnvVarName} points at a missing file: {fromEnv}");
            }

            // 3. Bundled venv next to the add-in (Windows layout).
            string bundledScript = Path.Combine(_addinDir, "engine-venv", "Scripts", "ca-elevation.exe");
            if (_fileExists(bundledScript)) return Wrap(bundledScript);

            string bundledPython = Path.Combine(_addinDir, "engine-venv", "Scripts", "python.exe");
            if (_fileExists(bundledPython))
            {
                return new EngineCommand(bundledPython, new[] { "-m", "ca_elevation_engine.cli" });
            }

            // 4. Bare console script on PATH (resolved by the OS at launch).
            return new EngineCommand(ConsoleScript);
        }

        private static EngineCommand Wrap(string path)
        {
            // If the configured path is a python interpreter, invoke the module form;
            // otherwise treat it as the console script directly.
            string name = Path.GetFileNameWithoutExtension(path);
            if (name.Equals("python", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("python3", StringComparison.OrdinalIgnoreCase))
            {
                return new EngineCommand(path, new[] { "-m", "ca_elevation_engine.cli" });
            }
            return new EngineCommand(path);
        }
    }
}
