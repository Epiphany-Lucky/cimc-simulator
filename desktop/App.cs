using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace CimcStudio;

public sealed class App : Application
{
    private Process? engine;
    private string root = "";
    private readonly List<string> engineLog = new();
    private bool exiting;

    [STAThread]
    public static void Main(string[] args)
    {
        var app = new App();
        app.Startup += async (_, _) => await app.StartAsync(args);
        app.Exit += (_, _) => app.StopEngine();
        app.Run();
    }

    private async Task StartAsync(string[] args)
    {
        try
        {
            root = LocateRoot();
            int port = FindPort();
            string url = $"http://127.0.0.1:{port}/";
            var window = new Window
            {
                Title = "CIMC Studio · 0.1.0",
                Width = 1480, Height = 960, MinWidth = 1080, MinHeight = 720,
                WindowStartupLocation = WindowStartupLocation.CenterScreen,
                Background = new SolidColorBrush(Color.FromRgb(245, 245, 247)),
                FontFamily = new FontFamily("Segoe UI")
            };
            MainWindow = window;
            var loading = new StackPanel { VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center };
            loading.Children.Add(new TextBlock { Text = "CIMC Studio", FontSize = 32, FontWeight = FontWeights.SemiBold, HorizontalAlignment = HorizontalAlignment.Center });
            loading.Children.Add(new TextBlock { Text = "正在启动本地仿真内核…", FontSize = 14, Foreground = Brushes.Gray, Margin = new Thickness(0, 16, 0, 0), HorizontalAlignment = HorizontalAlignment.Center });
            window.Content = loading;
            window.Closed += (_, _) => { StopEngine(); Shutdown(); };
            window.Show();
            StartEngine(port);
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            bool ready = false;
            for (int i = 0; i < 120; i++)
            {
                if (engine?.HasExited == true) throw new InvalidOperationException("仿真内核未能启动。\n" + RecentLog());
                try
                {
                    using var response = await client.GetAsync(url + "api/state");
                    if (response.IsSuccessStatusCode) { ready = true; break; }
                }
                catch (HttpRequestException) { }
                catch (TaskCanceledException) { }
                await Task.Delay(250);
            }
            if (!ready) throw new TimeoutException("等待本地仿真内核超时。\n" + RecentLog());
            if (args.Contains("--web"))
            {
                window.Width = 540; window.Height = 290; window.MinWidth = 480; window.MinHeight = 250;
                loading.Children.Clear();
                loading.Children.Add(new TextBlock { Text = "网页版已准备好", FontSize = 26, FontWeight = FontWeights.SemiBold });
                loading.Children.Add(new TextBlock { Text = url, FontSize = 15, Margin = new Thickness(0, 12, 0, 20) });
                var open = new Button { Content = "在浏览器中打开", Padding = new Thickness(20, 10, 20, 10) };
                open.Click += (_, _) => OpenBrowser(url);
                loading.Children.Add(open);
                loading.Children.Add(new TextBlock { Text = "保持此窗口开启。关闭后，本地内核会停止。", Foreground = Brushes.Gray, Margin = new Thickness(0, 16, 0, 0) });
                OpenBrowser(url);
                return;
            }
            try
            {
                var web = new WebView2 { DefaultBackgroundColor = System.Drawing.Color.FromArgb(245, 245, 247) };
                window.Content = web;
                var dataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CIMCStudio", "WebView2");
                var environment = await CoreWebView2Environment.CreateAsync(null, dataDir);
                await web.EnsureCoreWebView2Async(environment);
                web.CoreWebView2.Settings.IsStatusBarEnabled = false;
                web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                web.CoreWebView2.NewWindowRequested += (_, e) =>
                {
                    e.Handled = true;
                    if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri) && (uri.Scheme == "https" || uri.Scheme == "http")) OpenBrowser(e.Uri);
                };
                web.Source = new Uri(url);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                window.Content = loading;
                loading.Children.Clear();
                loading.Children.Add(new TextBlock { Text = "正在使用浏览器运行", FontSize = 26 });
                loading.Children.Add(new TextBlock { Text = "未检测到 Edge WebView2 运行时，已打开同一网页版。\n保持此窗口开启以运行本地内核。", Margin = new Thickness(0, 16, 0, 0) });
                OpenBrowser(url);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "CIMC Studio 启动失败", MessageBoxButton.OK, MessageBoxImage.Error);
            StopEngine(); Shutdown(1);
        }
    }

    private void StartEngine(int port)
    {
        var packaged = Path.Combine(root, "CIMC-Engine.exe");
        ProcessStartInfo info;
        if (File.Exists(packaged)) info = new ProcessStartInfo(packaged);
        else
        {
            var python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            if (!File.Exists(python)) throw new FileNotFoundException("未找到仿真内核。请解压完整发行包，或先运行 scripts/setup.ps1。", packaged);
            info = new ProcessStartInfo(python);
            info.ArgumentList.Add(Path.Combine(root, "engine", "server.py"));
        }
        info.ArgumentList.Add("--port"); info.ArgumentList.Add(port.ToString());
        info.ArgumentList.Add("--web-root"); info.ArgumentList.Add(Path.Combine(root, "web"));
        info.WorkingDirectory = root;
        info.CreateNoWindow = true; info.UseShellExecute = false;
        info.RedirectStandardError = true; info.RedirectStandardOutput = true;
        info.Environment["PYTHONIOENCODING"] = "utf-8";
        engine = new Process { StartInfo = info };
        engine.OutputDataReceived += (_, e) => RecordLog(e.Data);
        engine.ErrorDataReceived += (_, e) => RecordLog(e.Data);
        engine.Start(); engine.BeginOutputReadLine(); engine.BeginErrorReadLine();
    }

    private void RecordLog(string? value)
    {
        if (value is null) return;
        lock (engineLog) { engineLog.Add(value); if (engineLog.Count > 80) engineLog.RemoveAt(0); }
    }
    private string RecentLog() { lock (engineLog) return string.Join("\n", engineLog.TakeLast(12)); }
    private void StopEngine()
    {
        if (exiting) return; exiting = true;
        try { if (engine is { HasExited: false }) { engine.Kill(entireProcessTree: true); engine.WaitForExit(3000); } } catch (InvalidOperationException) { }
        engine?.Dispose();
    }
    private static string LocateRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "web", "index.html"))) return directory.FullName;
            directory = directory.Parent;
        }
        throw new DirectoryNotFoundException("未找到 web/index.html。请保留发行包目录结构。");
    }
    private static int FindPort()
    {
        for (int port = 8765; port < 8865; port++)
        {
            try { var listener = new TcpListener(IPAddress.Loopback, port); listener.Start(); listener.Stop(); return port; }
            catch (SocketException) { }
        }
        throw new IOException("无法分配本地服务端口。");
    }
    private static void OpenBrowser(string url) => Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
}
