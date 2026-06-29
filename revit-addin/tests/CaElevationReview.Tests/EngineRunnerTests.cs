using System.Collections.Generic;
using System.Diagnostics;
using CaElevationReview.Addin.Engine;
using Xunit;

namespace CaElevationReview.Tests
{
    /// <summary>
    /// Tests the pure, platform-agnostic parts of the engine bridge: argument building
    /// and CLI resolution. No child process is launched.
    /// </summary>
    public sealed class EngineRunnerTests
    {
        private static EngineRunRequest SampleRequest() => new EngineRunRequest
        {
            ManifestPath = @"C:\bundle\spec_manifest.json",
            CapturePath = @"C:\captures\capture_package.json",
            OutputDir = @"C:\captures\ca-elevation-out",
        };

        [Fact]
        public void BuildStartInfo_EmitsExactCliContract()
        {
            // Force a known executable via an injected locator so the assertion is stable.
            var locator = new EngineLocator(explicitPath: @"C:\tools\ca-elevation.exe", fileExists: _ => true);
            var runner = new EngineRunner(locator);

            ProcessStartInfo psi = runner.BuildStartInfo(SampleRequest());

            Assert.Equal(@"C:\tools\ca-elevation.exe", psi.FileName);
            Assert.Equal(
                new[]
                {
                    "run",
                    "--manifest", @"C:\bundle\spec_manifest.json",
                    "--capture", @"C:\captures\capture_package.json",
                    "--out", @"C:\captures\ca-elevation-out",
                },
                psi.ArgumentList);

            Assert.True(psi.RedirectStandardOutput);
            Assert.True(psi.RedirectStandardError);
            Assert.False(psi.UseShellExecute);
        }

        [Fact]
        public void BuildStartInfo_PrependsLocatorPrefixArgs_ForPythonModuleInvocation()
        {
            // A python interpreter path resolves to "python -m ca_elevation_engine.cli run ...".
            var locator = new EngineLocator(explicitPath: @"C:\venv\Scripts\python.exe", fileExists: _ => true);
            var runner = new EngineRunner(locator);

            ProcessStartInfo psi = runner.BuildStartInfo(SampleRequest());

            Assert.Equal(@"C:\venv\Scripts\python.exe", psi.FileName);
            Assert.Equal("-m", psi.ArgumentList[0]);
            Assert.Equal("ca_elevation_engine.cli", psi.ArgumentList[1]);
            Assert.Equal("run", psi.ArgumentList[2]);
        }

        [Fact]
        public void DescribeCommand_QuotesPathsWithSpaces()
        {
            var locator = new EngineLocator(explicitPath: @"C:\Program Files\ca-elevation.exe", fileExists: _ => true);
            var runner = new EngineRunner(locator);

            string desc = runner.DescribeCommand(SampleRequest());

            Assert.Contains("\"C:\\Program Files\\ca-elevation.exe\"", desc);
            Assert.Contains("--manifest", desc);
        }

        [Theory]
        [InlineData(null)]
        [InlineData("")]
        public void BuildStartInfo_RejectsMissingManifest(string? manifestPath)
        {
            var locator = new EngineLocator(explicitPath: @"C:\tools\ca-elevation.exe", fileExists: _ => true);
            var runner = new EngineRunner(locator);

            var request = SampleRequest();
            request.ManifestPath = manifestPath!;

            Assert.ThrowsAny<System.ArgumentException>(() => runner.BuildStartInfo(request));
        }
    }

    /// <summary>Resolution-order tests for <see cref="EngineLocator"/>.</summary>
    public sealed class EngineLocatorTests
    {
        [Fact]
        public void Resolve_PrefersExplicitPath_WhenItExists()
        {
            var locator = new EngineLocator(explicitPath: @"C:\custom\ca-elevation.exe", fileExists: _ => true);
            EngineCommand cmd = locator.Resolve();

            Assert.Equal(@"C:\custom\ca-elevation.exe", cmd.Executable);
            Assert.Empty(cmd.PrefixArgs);
        }

        [Fact]
        public void Resolve_ThrowsWhenExplicitPathMissing()
        {
            var locator = new EngineLocator(explicitPath: @"C:\nope\ca-elevation.exe", fileExists: _ => false);
            Assert.Throws<EngineNotFoundException>(() => locator.Resolve());
        }

        [Fact]
        public void Resolve_UsesEnvVar_WhenNoExplicitPath()
        {
            var env = new Dictionary<string, string?> { [EngineLocator.EnvVarName] = @"C:\fromenv\ca-elevation.exe" };
            var locator = new EngineLocator(
                fileExists: p => p == @"C:\fromenv\ca-elevation.exe",
                envReader: k => env.TryGetValue(k, out var v) ? v : null);

            EngineCommand cmd = locator.Resolve();
            Assert.Equal(@"C:\fromenv\ca-elevation.exe", cmd.Executable);
        }

        [Fact]
        public void Resolve_FallsBackToBareConsoleScript_OnPath()
        {
            // Nothing exists on disk, no env var -> the PATH-resolved console script.
            var locator = new EngineLocator(fileExists: _ => false, envReader: _ => null);
            EngineCommand cmd = locator.Resolve();

            Assert.Equal("ca-elevation", cmd.Executable);
            Assert.Empty(cmd.PrefixArgs);
        }
    }
}
