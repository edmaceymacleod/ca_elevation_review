using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using CaElevationReview.Addin.Verdict;

namespace CaElevationReview.Addin.Engine
{
    // Out-of-process bridge to the CPython engine. This is PURE platform-agnostic
    // code (System.Diagnostics, no Revit) and is the genuinely functional core of
    // the add-in: it builds the CLI invocation, runs it, captures stdout/stderr,
    // and parses the resulting verdict_report.json.
    //
    // CLI contract (see engine/pyproject.toml [project.scripts]):
    //   ca-elevation run --manifest <m> --capture <c> --out <dir>
    //   => writes <dir>/verdict_report.json
    //
    // The engine ships heavy native wheels (Open3D/pye57/OpenCV) that are fragile
    // to load inside Revit's own process, which is exactly why this runs as a
    // child process rather than embedded.

    /// <summary>Inputs for a single engine run.</summary>
    public sealed class EngineRunRequest
    {
        /// <summary>Absolute path to the spec_manifest.json written by the add-in.</summary>
        public string ManifestPath { get; set; } = string.Empty;

        /// <summary>Absolute path to the capture package returned from the field.</summary>
        public string CapturePath { get; set; } = string.Empty;

        /// <summary>Absolute path to the output directory; the engine writes verdict_report.json here.</summary>
        public string OutputDir { get; set; } = string.Empty;
    }

    /// <summary>Result of an engine run: exit code, captured streams, and the parsed report on success.</summary>
    public sealed class EngineRunResult
    {
        public int ExitCode { get; set; }
        public string StdOut { get; set; } = string.Empty;
        public string StdErr { get; set; } = string.Empty;

        /// <summary>The path the report was expected at, whether or not it materialized.</summary>
        public string ReportPath { get; set; } = string.Empty;

        /// <summary>Parsed report; null if the run failed or the file was absent/unparseable.</summary>
        public VerdictReport? Report { get; set; }

        public bool Succeeded => ExitCode == 0 && Report != null;
    }

    /// <summary>Raised when the engine cannot be located on the host.</summary>
    public sealed class EngineNotFoundException : Exception
    {
        public EngineNotFoundException(string message) : base(message) { }
    }

    /// <summary>
    /// Locates and invokes the <c>ca-elevation</c> CLI out-of-process, then reads back
    /// the verdict report. All file-system and process interaction is funneled through
    /// here so it can be stubbed in tests; the argument/command building is exposed
    /// separately (<see cref="BuildStartInfo"/>) for pure unit testing.
    /// </summary>
    public sealed class EngineRunner
    {
        /// <summary>The filename the engine writes into the output dir, per the CLI contract.</summary>
        public const string ReportFileName = "verdict_report.json";

        private readonly EngineLocator _locator;

        public EngineRunner(EngineLocator? locator = null)
        {
            _locator = locator ?? new EngineLocator();
        }

        /// <summary>
        /// Build the <see cref="ProcessStartInfo"/> for a run without launching it.
        /// Separated out so argument construction is unit-testable with no live process.
        /// </summary>
        public ProcessStartInfo BuildStartInfo(EngineRunRequest request)
        {
            if (request == null) throw new ArgumentNullException(nameof(request));
            ValidateRequest(request);

            EngineCommand cmd = _locator.Resolve();

            var psi = new ProcessStartInfo
            {
                FileName = cmd.Executable,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                WorkingDirectory = request.OutputDir,
            };

            // Any prefix args the locator needs (e.g. ["-m", "ca_elevation_engine.cli"]
            // when invoking via "python -m" instead of the console script) come first.
            foreach (string prefix in cmd.PrefixArgs)
            {
                psi.ArgumentList.Add(prefix);
            }

            psi.ArgumentList.Add("run");
            psi.ArgumentList.Add("--manifest");
            psi.ArgumentList.Add(request.ManifestPath);
            psi.ArgumentList.Add("--capture");
            psi.ArgumentList.Add(request.CapturePath);
            psi.ArgumentList.Add("--out");
            psi.ArgumentList.Add(request.OutputDir);

            return psi;
        }

        /// <summary>
        /// Render the resolved command + args as a single shell-ish string, for logging
        /// and for asserting in tests. Not used to actually launch (ArgumentList is).
        /// </summary>
        public string DescribeCommand(EngineRunRequest request)
        {
            ProcessStartInfo psi = BuildStartInfo(request);
            var sb = new StringBuilder();
            sb.Append(Quote(psi.FileName));
            foreach (string arg in psi.ArgumentList)
            {
                sb.Append(' ').Append(Quote(arg));
            }
            return sb.ToString();
        }

        /// <summary>
        /// Run the engine to completion, capturing both streams, then load the report.
        /// </summary>
        /// <param name="request">Manifest/capture/output paths.</param>
        /// <param name="onProgressLine">Optional callback fired per stdout line (for a progress UI).</param>
        /// <param name="cancellation">Cancels by killing the child process.</param>
        public async Task<EngineRunResult> RunAsync(
            EngineRunRequest request,
            Action<string>? onProgressLine = null,
            CancellationToken cancellation = default)
        {
            ProcessStartInfo psi = BuildStartInfo(request);

            Directory.CreateDirectory(request.OutputDir);

            var stdout = new StringBuilder();
            var stderr = new StringBuilder();

            using var process = new Process { StartInfo = psi, EnableRaisingEvents = true };

            process.OutputDataReceived += (_, e) =>
            {
                if (e.Data == null) return;
                stdout.AppendLine(e.Data);
                onProgressLine?.Invoke(e.Data);
            };
            process.ErrorDataReceived += (_, e) =>
            {
                if (e.Data != null) stderr.AppendLine(e.Data);
            };

            try
            {
                process.Start();
            }
            catch (Exception ex)
            {
                throw new EngineNotFoundException(
                    $"Failed to launch engine '{psi.FileName}'. Confirm the CLI is installed " +
                    $"or configure its path. Inner: {ex.Message}");
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();

            using (cancellation.Register(() => TryKill(process)))
            {
                await WaitForExitAsync(process, cancellation).ConfigureAwait(false);
            }

            var result = new EngineRunResult
            {
                ExitCode = process.ExitCode,
                StdOut = stdout.ToString(),
                StdErr = stderr.ToString(),
                ReportPath = Path.Combine(request.OutputDir, ReportFileName),
            };

            if (result.ExitCode == 0 && File.Exists(result.ReportPath))
            {
                string json = File.ReadAllText(result.ReportPath);
                result.Report = VerdictReport.FromJson(json);
            }

            return result;
        }

        private static void ValidateRequest(EngineRunRequest request)
        {
            if (string.IsNullOrWhiteSpace(request.ManifestPath))
                throw new ArgumentException("ManifestPath is required.", nameof(request));
            if (string.IsNullOrWhiteSpace(request.CapturePath))
                throw new ArgumentException("CapturePath is required.", nameof(request));
            if (string.IsNullOrWhiteSpace(request.OutputDir))
                throw new ArgumentException("OutputDir is required.", nameof(request));
        }

        private static void TryKill(Process process)
        {
            try
            {
                if (!process.HasExited)
                {
#if NET8_0_OR_GREATER
                    process.Kill(entireProcessTree: true);
#else
                    process.Kill();
#endif
                }
            }
            catch
            {
                // Best-effort; the process may have exited between the check and the kill.
            }
        }

        /// <summary>
        /// Await process exit cooperatively. (net48 lacks Process.WaitForExitAsync, so
        /// we bridge the Exited event to a TaskCompletionSource.)
        /// </summary>
        private static Task WaitForExitAsync(Process process, CancellationToken cancellation)
        {
            var tcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            process.Exited += (_, _) => tcs.TrySetResult(true);

            // Cover the race where the process exited before the handler was attached.
            if (process.HasExited) tcs.TrySetResult(true);

            cancellation.Register(() => tcs.TrySetCanceled(cancellation));
            return tcs.Task;
        }

        private static string Quote(string value)
            => value.IndexOf(' ') >= 0 ? "\"" + value + "\"" : value;
    }
}
