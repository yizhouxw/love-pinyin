using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Launcher {
    const int Port = 18765;
    static string Q(string path) { return "\"" + path.Replace("\"", "") + "\""; }
    static string FindEdge() {
        foreach (RegistryHive root in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
            foreach (RegistryView view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
                using (var baseKey = RegistryKey.OpenBaseKey(root, view))
                using (var key = baseKey.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe")) {
                    var path = key == null ? null : key.GetValue(null) as string;
                    if (!String.IsNullOrEmpty(path) && File.Exists(path)) return path;
                }
        return null;
    }
    [STAThread]
    static void Main() {
        bool created;
        using (var mutex = new Mutex(true, @"Local\LovePinyinDesktop", out created)) {
            if (!created) { MessageBox.Show("爱拼音已经运行。", "爱拼音"); return; }
            Process server = null;
            try {
                string edge = FindEdge();
                if (edge == null) throw new Exception("请先安装 Microsoft Edge，然后重新打开爱拼音。");
                var check = new TcpListener(IPAddress.Loopback, Port);
                try { check.Start(); } catch (SocketException) { throw new Exception("本机端口 18765 已被占用，请关闭占用该端口的程序后重试。"); } finally { check.Stop(); }
                string root = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "app");
                string python = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "python", "python.exe");
                string data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LovePinyin");
                Directory.CreateDirectory(data);
                var start = new ProcessStartInfo(python, "-m uvicorn server.main:app --host 127.0.0.1 --port 18765 --no-proxy-headers");
                start.WorkingDirectory = root; start.UseShellExecute = false; start.CreateNoWindow = true;
                start.EnvironmentVariables["LOVE_PINYIN_DATA_DIR"] = Path.Combine(data, "data");
                start.EnvironmentVariables["LOVE_PINYIN_ASR_CPU_ONLY"] = "1";
                start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
                start.EnvironmentVariables["PYTHONUTF8"] = "1";
                server = Process.Start(start);
                bool ready = false;
                for (int i = 0; i < 100 && !server.HasExited; i++) {
                    try { var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:18765/api/v1/health"); request.Proxy = null; request.Timeout = 500; using (var response = (HttpWebResponse)request.GetResponse()) { ready = response.StatusCode == HttpStatusCode.OK; } if (ready) break; } catch (WebException) { Thread.Sleep(200); }
                }
                if (!ready) throw new Exception("本地服务未能启动，请重新打开应用。");
                var browser = new ProcessStartInfo(edge, "--no-first-run --user-data-dir=" + Q(Path.Combine(data, "browser")) + " --app=http://127.0.0.1:18765/");
                browser.UseShellExecute = false;
                using (var process = Process.Start(browser)) process.WaitForExit();
            } catch (Exception e) { MessageBox.Show(e.Message, "爱拼音无法启动", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            finally { if (server != null) { try { if (!server.HasExited) { server.Kill(); server.WaitForExit(); } } catch (InvalidOperationException) {} server.Dispose(); } }
        }
    }
}
