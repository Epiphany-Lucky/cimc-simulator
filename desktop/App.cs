using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
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
            var workArea = SystemParameters.WorkArea;
            var window = new Window
            {
                Title = "CIMC Studio · 0.4.0",
                Width = Math.Min(1280, Math.Max(320, workArea.Width - 32)),
                Height = Math.Min(820, Math.Max(240, workArea.Height - 32)),
                WindowStartupLocation = WindowStartupLocation.CenterScreen,
                Background = new SolidColorBrush(Color.FromRgb(245, 245, 247)),
                FontFamily = new FontFamily("Segoe UI")
            };
            MainWindow = window;
            window.SourceInitialized += (_, _) =>
            {
                var source = HwndSource.FromHwnd(new WindowInteropHelper(window).Handle);
                source?.AddHook((IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled) =>
                {
                    // Recheck after DPI, monitor/work-area changes, or a completed resize/move.
                    if (message is 0x02E0 or 0x007E or 0x001A or 0x0232)
                        window.Dispatcher.BeginInvoke(new Action(() => FitWindow(window, false)));
                    return IntPtr.Zero;
                });
            };
            window.Loaded += (_, _) => FitWindow(window, true);
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
                if (exiting) return;
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
                window.Tag = "service";
                window.Width = 540; window.Height = 290; window.MinWidth = 480; window.MinHeight = 250;
                FitWindow(window, true);
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

    private static void FitWindow(Window window, bool center)
    {
        if (!window.IsVisible || window.WindowState != WindowState.Normal) return;
        var handle = new WindowInteropHelper(window).Handle;
        var info = new MonitorInfo { Size = Marshal.SizeOf<MonitorInfo>() };
        if (!GetMonitorInfo(MonitorFromWindow(handle, 2), ref info) || !GetWindowRect(handle, out var bounds)) return;
        var dpi = GetDpiForWindow(handle);
        double scale = dpi == 0 ? 1 : dpi / 96.0;
        var work = info.Work;
        int margin = Math.Min(16, Math.Max(0, Math.Min(work.Right - work.Left, work.Bottom - work.Top) / 40));
        double maxWidth = Math.Max(1, (work.Right - work.Left - 2 * margin) / scale);
        double maxHeight = Math.Max(1, (work.Bottom - work.Top - 2 * margin) / scale);
        bool serviceWindow = Equals(window.Tag, "service");
        window.MinWidth = Math.Min(serviceWindow ? 480 : 760, maxWidth);
        window.MinHeight = Math.Min(serviceWindow ? 250 : 480, maxHeight);
        window.Width = Math.Clamp(window.Width, window.MinWidth, maxWidth);
        window.Height = Math.Clamp(window.Height, window.MinHeight, maxHeight);
        int width = (int)Math.Round(window.Width * scale);
        int height = (int)Math.Round(window.Height * scale);
        int left = center ? work.Left + (work.Right - work.Left - width) / 2
                          : Math.Clamp(bounds.Left, work.Left + margin, work.Right - margin - width);
        int top = center ? work.Top + (work.Bottom - work.Top - height) / 2
                         : Math.Clamp(bounds.Top, work.Top + margin, work.Bottom - margin - height);
        SetWindowPos(handle, IntPtr.Zero, left, top, width, height, 0x0004 | 0x0010);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeRect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    private struct MonitorInfo { public int Size; public NativeRect Monitor, Work; public uint Flags; }
    [DllImport("user32.dll")] private static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hwnd, out NativeRect rect);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);

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
