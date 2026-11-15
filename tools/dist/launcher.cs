// 配布物の起動用の小さな exe（tools/dist/build_embed.py が Windows に入っている .NET Framework 4 の csc.exe で作る・C# 5 の書き方だけ）。
// ふだん: 自分の隣の runtime\pythonw.exe で app\desktop.py（窓のアプリ）を起動して、その窓が出たら終わる（黒い窓は出ない）。
//   窓が 0.5 秒で出なければ、出るまで小さな「起動しています」の窓を出す（WaitShown）。窓を出さずに失敗で終わったら記録の場所を知らせる。
// - 利用者の PC にほかの Python があっても混ざらないように、PYTHONHOME・PYTHONPATH 等を消し、ユーザーごとの site-packages を切る
//   （PYTHONNOUSERSITE=1）。子のプロセス（作り直しの compose・曲の解析）も同じ環境を受け継ぐ。
// - 引数はそのまま desktop.py へ渡す（--debug・--selftest 等）。
// 更新の差し替え役（--apply-update・app/update.py の③）: 古い版のアプリが、<アプリ>\_update\new\AutoNotePlotter\ に展開した
// 「新しい版の」この exe を `--apply-update --target <アプリのフォルダ> --pid <古いアプリのプロセス>` で起動して終わる。この exe は
// 古いアプリが終わるのを待ってから、ReplaceItems を <アプリ>\_previous_<古い版>\ へ退避し、新しい版の物を置き、アプリを起動し直す。
// 失敗したら退避した物を戻して古い版のまま起動し直す（NLM の app_update.apply_main と同じ）。
// ★版をまたぐ約束（app/update.py の頭）: この引数（--apply-update --target --pid）を受け付け続けること・自分が
//   <target>\_update\new\AutoNotePlotter\ にいる時だけ動く・差し替えるのは ReplaceItems だけ（利用者のデータはアプリのフォルダの外）。
//   確かめ用の引数: --no-launch（起動し直さない）・--quiet（窓・知らせを出さない＝終了コードだけ。0＝できた・1＝失敗して戻した・
//   2＝場所か中身が違う・3＝古いアプリが終わらない）。
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Auto Note Plotter")]
[assembly: AssemblyProduct("Auto Note Plotter")]
[assembly: AssemblyVersion("0.0.0.0")]

static class Launcher
{
    public const string Title = "Auto Note Plotter";
    public const string ExeName = "AutoNotePlotter.exe";

    // Windows のコマンドラインの決まり（CommandLineToArgvW）で 1 つの引数を囲む
    static string Quote(string a)
    {
        if (a.Length > 0 && a.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0) return a;
        var sb = new StringBuilder("\"");
        int bs = 0;
        foreach (char ch in a)
        {
            if (ch == '\\') { bs++; continue; }
            if (ch == '"') { sb.Append('\\', bs * 2 + 1); sb.Append('"'); bs = 0; continue; }
            sb.Append('\\', bs); bs = 0; sb.Append(ch);
        }
        sb.Append('\\', bs * 2);
        sb.Append('"');
        return sb.ToString();
    }

    [STAThread]
    static int Main(string[] args)
    {
        if (Array.IndexOf(args, "--apply-update") >= 0)
            return ApplyUpdate.Run(args);
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string pyw = Path.Combine(root, Path.Combine("runtime", "pythonw.exe"));
        string main = Path.Combine(root, Path.Combine("app", "desktop.py"));
        if (!File.Exists(pyw) || !File.Exists(main))
        {
            MessageBox.Show("中身が足りません（runtime\\pythonw.exe か app\\desktop.py が無い）。\n配布の zip をもう一度展開してください。\n\n" + root,
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var cmd = new StringBuilder(Quote(main));
        foreach (string a in args) { cmd.Append(' '); cmd.Append(Quote(a)); }
        var psi = new ProcessStartInfo(pyw, cmd.ToString());
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        foreach (string k in new string[] { "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE", "PYTHONSAFEPATH" })
            psi.EnvironmentVariables.Remove(k);
        psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        Process child;
        try
        {
            child = Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("起動できませんでした: " + e.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        if (child != null) WaitShown(child);
        return 0;
    }

    // 窓のアプリ（pythonw）の窓が出たか（起動の表示の窓・desktop.py の知らせ＝MessageBox も窓）
    static bool HasWindow(Process p)
    {
        try { p.Refresh(); return !p.HasExited && p.MainWindowHandle != IntPtr.Zero; }
        catch (Exception) { return false; }
    }

    // 起動の表示（2026-11-09）: pythonw が窓を出すまで（Python と窓の部品の読み込み・初めての起動はウイルス対策ソフトの検査で数秒〜）
    // 小さな窓を出す。0.5 秒以内に窓が出れば何も出さない。pythonw が窓を出さずに失敗で終わったら記録の場所を知らせる
    // （desktop.py が自分で知らせる失敗は、その知らせが窓なのでここでは出さない）。120 秒で窓を閉じて終わる（pythonw はそのまま）
    static void WaitShown(Process p)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < 500)
        {
            if (HasWindow(p)) return;
            if (p.HasExited) { Exited(p); return; }
            Thread.Sleep(50);
        }
        bool exited = false;
        Application.EnableVisualStyles();
        var form = new Form();
        form.Text = Title;
        form.FormBorderStyle = FormBorderStyle.FixedDialog;
        form.ControlBox = false;
        form.StartPosition = FormStartPosition.CenterScreen;
        form.ClientSize = new Size(460, 110);
        try { form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }
        var head = new Label();
        head.Text = "Auto Note Plotter を起動しています…";
        head.Font = new Font(SystemFonts.MessageBoxFont, FontStyle.Bold);
        head.SetBounds(16, 12, 428, 22);
        var note = new Label();
        note.Text = "初めての起動・パソコンを起動し直した直後は、少し時間がかかります。";
        note.SetBounds(16, 38, 428, 22);
        var bar = new ProgressBar();
        bar.Style = ProgressBarStyle.Marquee;
        bar.MarqueeAnimationSpeed = 30;
        bar.SetBounds(16, 70, 428, 18);
        form.Controls.Add(head);
        form.Controls.Add(note);
        form.Controls.Add(bar);
        var timer = new System.Windows.Forms.Timer();
        timer.Interval = 100;
        timer.Tick += (s, e) =>
        {
            if (HasWindow(p) || sw.Elapsed.TotalSeconds > 120) { timer.Stop(); form.Close(); return; }
            bool gone;
            try { gone = p.HasExited; } catch (Exception) { gone = true; }
            if (gone) { exited = true; timer.Stop(); form.Close(); }
        };
        form.Shown += (s, e) => timer.Start();
        Application.Run(form);
        if (exited) Exited(p);
    }

    // pythonw が窓を出さずに終わった: 失敗（終了コードが 0 でない）なら記録の場所を知らせる
    static void Exited(Process p)
    {
        int code;
        try { code = p.ExitCode; } catch (Exception) { return; }
        if (code == 0) return;
        string log = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Path.Combine("automap-app", "desktop.log"));
        MessageBox.Show("Auto Note Plotter を起動できませんでした（終了コード " + code + "）。\n\nもう一度起動してください。続く時は、次の記録を見せてください。\n" + log,
                        Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}

// ---- 更新の差し替え（app/update.py の③・NLM の app_update.apply_main の写し）----
static class ApplyUpdate
{
    const string ZipTop = "AutoNotePlotter";
    const string UpdateDir = "_update";
    const string PrevPrefix = "_previous_";
    // 差し替える物（これ以外には触らない・app/update.py の REPLACE_ITEMS と同じ）。どちらかの側に無い物は飛ばす。
    // 差し替えは新しい版の exe が自分の一覧で行うので、ここに足した物は古い版からの更新でも届く
    static readonly string[] ReplaceItems = { Launcher.ExeName, "runtime", "app", "automap", "tools", "data", "parts",
                                              "LICENSE", "THIRD_PARTY_NOTICES.md", "build-info.json" };
    static readonly Regex VerRe = new Regex("\"version\"\\s*:\\s*\"(v\\d{1,4}\\.\\d{1,4}\\.\\d{1,4})\"");

    static string logPath;
    static bool quiet;
    static Label label;
    static Form form;

    static string Arg(string[] a, string name, string def)
    {
        int i = Array.IndexOf(a, name);
        return i >= 0 && i + 1 < a.Length ? a[i + 1] : def;
    }

    static string Norm(string p)
    {
        return Path.GetFullPath(p).TrimEnd('\\', '/').ToLowerInvariant();
    }

    // build-info.json の "version"（v〇.〇.〇 の形だけ）。読めなければ ""
    static string ReadVersion(string dir)
    {
        try
        {
            var m = VerRe.Match(File.ReadAllText(Path.Combine(dir, "build-info.json"), Encoding.UTF8));
            return m.Success ? m.Groups[1].Value : "";
        }
        catch (Exception) { return ""; }
    }

    static void Log(string msg)
    {
        if (logPath == null) return;
        try { File.AppendAllText(logPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + msg + "\r\n", new UTF8Encoding(false)); }
        catch (Exception) { }
    }

    // 失敗の知らせ。差し替えの小さな窓が出ている間（別の流れ）は覚えておき、窓を閉じた後に出す
    static string pendingMsg;
    static void Show(string msg)
    {
        Log("失敗: " + msg.Replace("\n", " "));
        if (quiet) return;
        if (form != null) { pendingMsg = msg; return; }
        MessageBox.Show(msg, Launcher.Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    static void Say(string msg)
    {
        Log(msg);
        if (label == null) return;
        try { label.BeginInvoke(new Action(() => { label.Text = msg; })); } catch (Exception) { }
    }

    // pid のプロセスが終わるまで待つ。終わったら true（もう居ない・この exe より後に始まった別のプロセス＝番号の使い回しも true）
    static bool WaitPid(int pid, int ms)
    {
        if (pid <= 0) return true;
        Process p;
        try { p = Process.GetProcessById(pid); }
        catch (ArgumentException) { return true; }
        using (p)
        {
            try { if (p.StartTime > Process.GetCurrentProcess().StartTime) return true; } catch (Exception) { }
            try { return p.WaitForExit(ms); } catch (Exception) { return true; }
        }
    }

    // 終わった直後のプロセスがまだファイルを掴んでいることがあるので、少し待って何度か試す
    static void Retry(Action fn, int tries, int waitMs)
    {
        for (int i = 0; ; i++)
        {
            try { fn(); return; }
            catch (IOException) { if (i >= tries - 1) throw; }
            catch (UnauthorizedAccessException) { if (i >= tries - 1) throw; }
            Thread.Sleep(waitMs);
        }
    }

    static void MoveItem(string s, string d)
    {
        if (Directory.Exists(s)) Directory.Move(s, d); else File.Move(s, d);
    }

    static void DeleteTree(string p)
    {
        try
        {
            if (Directory.Exists(p))
            {
                foreach (string f in Directory.GetFiles(p, "*", SearchOption.AllDirectories))
                    File.SetAttributes(f, FileAttributes.Normal);
                Retry(() => Directory.Delete(p, true), 12, 250);   // 消した直後に「空ではない」と言われることがある（ウイルス対策・索引が掴む間）
            }
            else if (File.Exists(p))
            {
                File.SetAttributes(p, FileAttributes.Normal);
                File.Delete(p);
            }
        }
        catch (Exception e) { Log("消せなかった: " + p + " " + e.Message); }
    }

    public static int Run(string[] args)
    {
        quiet = Array.IndexOf(args, "--quiet") >= 0;
        bool launch = Array.IndexOf(args, "--no-launch") < 0;
        string targetArg = Arg(args, "--target", "");
        int pid;
        if (!int.TryParse(Arg(args, "--pid", "0"), out pid)) pid = 0;
        string src = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
        const string failTail = "\n\n手で更新する時は、配布元（GitHub）のリリースのページから zip をダウンロードし、展開した物で置き換えてください。";
        string target;
        try { target = Path.GetFullPath(targetArg).TrimEnd('\\', '/'); }
        catch (Exception) { Show("更新できませんでした（場所が正しくありません）。" + failTail); return 2; }
        // 自分が「target の _update\new\AutoNotePlotter」にいる時だけ動く（ほかのフォルダを書き換えさせない）
        if (targetArg.Length == 0 || Norm(src) != Norm(Path.Combine(target, Path.Combine(UpdateDir, Path.Combine("new", ZipTop))))
            || !File.Exists(Path.Combine(target, Launcher.ExeName)))
        {
            Show("更新できませんでした（更新の置き場所が正しくありません）。" + failTail);
            return 2;
        }
        logPath = Path.Combine(Path.Combine(target, UpdateDir), "apply.log");
        string newVer = ReadVersion(src);
        if (newVer.Length == 0 || !File.Exists(Path.Combine(src, Launcher.ExeName)))
        {
            Show("更新できませんでした（ダウンロードした版の中身が正しくありません）。" + failTail);
            return 2;
        }
        string oldVer = ReadVersion(target);
        Log("差し替えを始める: " + (oldVer.Length > 0 ? oldVer : "（版が読めない）") + " → " + newVer + "（待つプロセス " + pid + "）");
        int code = 1;
        if (quiet)
        {
            code = Work(target, src, pid, oldVer, newVer, failTail);
        }
        else
        {
            Application.EnableVisualStyles();
            form = new Form();
            form.Text = Launcher.Title;
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.ControlBox = false;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.ClientSize = new Size(460, 110);
            form.TopMost = true;
            try { form.Icon = Icon.ExtractAssociatedIcon(Path.Combine(src, Launcher.ExeName)); } catch (Exception) { }
            var head = new Label();
            head.Text = "Auto Note Plotter を " + newVer + " に更新しています";
            head.Font = new Font(SystemFonts.MessageBoxFont, FontStyle.Bold);
            head.SetBounds(16, 12, 428, 22);
            label = new Label();
            label.Text = "アプリが終わるのを待っています…";
            label.SetBounds(16, 38, 428, 22);
            var bar = new ProgressBar();
            bar.Style = ProgressBarStyle.Marquee;
            bar.MarqueeAnimationSpeed = 30;
            bar.SetBounds(16, 70, 428, 18);
            form.Controls.Add(head);
            form.Controls.Add(label);
            form.Controls.Add(bar);
            form.Shown += (s, e) =>
            {
                var th = new Thread(() =>
                {
                    code = Work(target, src, pid, oldVer, newVer, failTail);
                    try { form.BeginInvoke(new Action(() => form.Close())); } catch (Exception) { }
                });
                th.IsBackground = true;
                th.Start();
            };
            Application.Run(form);
            label = null;
            form = null;
            if (pendingMsg != null) MessageBox.Show(pendingMsg, Launcher.Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        // できた時も、失敗して古い版に戻した時も起動し直す（失敗の知らせは Work の中で出した）。古いアプリが終わらない時（3）は起動しない
        if ((code == 0 || code == 1) && launch)
        {
            try
            {
                var psi = new ProcessStartInfo(Path.Combine(target, Launcher.ExeName));
                psi.WorkingDirectory = target;
                psi.UseShellExecute = false;
                Process.Start(psi);
                Log("起動し直した");
            }
            catch (Exception e) { Log("起動し直せなかった: " + e.Message); }
        }
        return code;
    }

    // 差し替えの本体 → 0＝できた・1＝失敗して元に戻した・3＝古いアプリが終わらない
    static int Work(string target, string src, int pid, string oldVer, string newVer, string failTail)
    {
        if (!WaitPid(pid, 60000))
        {
            Show("Auto Note Plotter が終わらないため、更新できませんでした。\nアプリを閉じてから、もう一度「更新」の窓から更新してください。");
            return 3;
        }
        Say("前の版を退避しています…");
        string bk = Path.Combine(target, PrevPrefix + (oldVer.Length > 0 ? oldVer : "old"));
        var moved = new System.Collections.Generic.List<string>();
        var placed = new System.Collections.Generic.List<string>();
        string err = "";
        bool ok = false;
        try
        {
            foreach (string d in Directory.GetDirectories(target, PrevPrefix + "*"))   // 退避は 1 世代だけ
                DeleteTree(d);
            if (Directory.Exists(bk)) bk = bk + "_" + DateTime.Now.ToString("yyyyMMddHHmmss");   // 消せなかった時
            Directory.CreateDirectory(bk);
            foreach (string n in ReplaceItems)
            {
                string p = Path.Combine(target, n);
                if (Directory.Exists(p) || File.Exists(p))
                {
                    string dst = Path.Combine(bk, n);
                    Retry(() => MoveItem(p, dst), 120, 250);   // 30 秒まで（閉じたばかりのアプリ・作り直しの子のプロセスが掴んでいる間）
                    moved.Add(n);
                }
            }
            Say("新しい版を置いています…");
            foreach (string n in ReplaceItems)
            {
                string s = Path.Combine(src, n), d = Path.Combine(target, n);
                if (Directory.Exists(s))
                {
                    Retry(() => Directory.Move(s, d), 20, 250);   // 同じドライブの中＝すぐ終わる
                    placed.Add(n);
                }
                else if (File.Exists(s))
                {
                    File.Copy(s, d);   // 自分（動いている exe）も写すだけなら読める
                    placed.Add(n);
                }
            }
            if (ReadVersion(target) != newVer || !File.Exists(Path.Combine(target, Launcher.ExeName)))
                throw new IOException("置いた後の確かめに失敗した（版 " + ReadVersion(target) + "）");
            ok = true;
        }
        catch (Exception e)
        {
            err = e.Message;
            Log("失敗したので戻す: " + err);
            // 元に戻す: 途中まで置いた新しい版を展開した場所へ戻し（戻せなければ消し）、退避した古い版を戻す
            foreach (string n in placed)
            {
                string p = Path.Combine(target, n), s = Path.Combine(src, n);
                try
                {
                    if (Directory.Exists(p) && !Directory.Exists(s)) Directory.Move(p, s);
                    else DeleteTree(p);
                }
                catch (Exception) { DeleteTree(p); }
            }
            foreach (string n in moved)
            {
                string p = Path.Combine(target, n), b = Path.Combine(bk, n);
                try { Retry(() => MoveItem(b, p), 8, 250); }
                catch (Exception e2) { Log("戻せなかった: " + n + " " + e2.Message); }
            }
            try { Directory.Delete(bk); } catch (Exception) { }   // 全部戻せた時だけ空になる（戻せなかった物が残っていれば退避ごと残す）
        }
        if (ok)
        {
            try
            {
                File.WriteAllText(Path.Combine(Path.Combine(target, UpdateDir), "applied.json"),
                                  "{\"from\": \"" + (oldVer.Length > 0 ? oldVer : "old") + "\", \"to\": \"" + newVer + "\"}", new UTF8Encoding(false));
            }
            catch (Exception e) { Log("applied.json を書けなかった: " + e.Message); }
            Say("更新できました。起動し直します…");
            Log("できた: " + newVer);
            return 0;
        }
        Show("更新できませんでした。前の版のまま起動します。\n\n" + err + failTail);
        return 1;
    }
}
