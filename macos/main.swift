// Приложение для macOS: собственное окно, в котором открыт тот же интерфейс.
//
// Вся логика остаётся в Python. Оболочка делает три вещи:
//   1) запускает app.py на свободном порту своего компьютера (127.0.0.1);
//   2) показывает его страницу в окне;
//   3) завершает app.py, когда окно закрыто.
// Наружу данные не уходят: сервер слушает только этот компьютер.

import Cocoa
import UniformTypeIdentifiers
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    // Сервер следит за этим каналом: пока приложение живо, канал открыт.
    // Если приложение закроется, даже аварийно, канал оборвётся и сервер завершится сам.
    private let serverInput = Pipe()
    private var serverStarted = false
    private var failed = false
    // Режим самопроверки сборки: ContractCheck --selftest
    private let selfTest = CommandLine.arguments.contains("--selftest")

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        startServer()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) { server?.terminate() }

    // MARK: Окно и меню

    private func buildWindow() {
        let frame = NSRect(x: 0, y: 0, width: 1400, height: 900)
        window = NSWindow(contentRect: frame,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Проверка условий договоров поставки"
        window.minSize = NSSize(width: 720, height: 520)
        window.center()
        window.setFrameAutosaveName("MainWindow")     // запоминает размер и положение окна

        webView = WKWebView(frame: frame)
        webView.uiDelegate = self
        webView.navigationDelegate = self
        webView.loadHTMLString("<p style=\"font: 15px -apple-system; padding: 24px; color: gray\">Запуск…</p>",
                               baseURL: nil)
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func buildMenu() {
        let mainMenu = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "О программе",
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Скрыть", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Завершить", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        // Без меню «Правка» в окне не работают ⌘C и ⌘A.
        let editMenu = NSMenu(title: "Правка")
        editMenu.addItem(withTitle: "Копировать", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Вставить", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Выбрать всё", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        let windowMenu = NSMenu(title: "Окно")
        windowMenu.addItem(withTitle: "Свернуть", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Закрыть", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")

        for menu in [appMenu, editMenu, windowMenu] {
            let item = NSMenuItem()
            item.submenu = menu
            mainMenu.addItem(item)
        }
        NSApp.mainMenu = mainMenu
    }

    // MARK: Запуск программы на Python

    private func startServer() {
        guard let appDir = Bundle.main.resourceURL?.appendingPathComponent("app"),
              FileManager.default.fileExists(atPath: appDir.appendingPathComponent("app.py").path) else {
            return fail("Внутри приложения нет файлов программы. Соберите его заново: macos/build.sh")
        }
        let candidates = ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
        guard let python = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            return fail("Не найден Python 3. Его можно установить командой: xcode-select --install")
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        // -B: не записывать служебные файлы внутрь приложения; -u: отдавать вывод сразу;
        // --port 0: взять любой свободный порт
        process.arguments = ["-B", "-u", appDir.appendingPathComponent("app.py").path,
                             "--port", "0", "--exit-with-parent"]
        process.standardInput = serverInput

        // Сервер печатает адрес, на котором он запустился. Читаем его и открываем в окне.
        let output = Pipe()
        process.standardOutput = output
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            let text = String(data: data, encoding: .utf8) ?? ""
            guard let range = text.range(of: #"http://127\.0\.0\.1:\d+"#, options: .regularExpression),
                  let url = URL(string: String(text[range])) else { return }
            handle.readabilityHandler = nil
            DispatchQueue.main.async {
                self?.serverStarted = true
                self?.webView.load(URLRequest(url: url))
            }
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                if self?.serverStarted == false {
                    self?.fail("Программа не запустилась. Проверьте, что установлен Python 3.9 или новее.")
                }
            }
        }

        do {
            try process.run()
            server = process
        } catch {
            return fail("Не удалось запустить Python: \(error.localizedDescription)")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            if self?.serverStarted == false { self?.fail("Программа не ответила за 15 секунд.") }
        }
        if selfTest {
            DispatchQueue.main.asyncAfter(deadline: .now() + 40) { [weak self] in
                self?.fail("самопроверка не завершилась за 40 секунд")
            }
        }
    }

    private func fail(_ message: String) {
        if failed { return }
        failed = true
        if selfTest {
            print("SELFTEST FAIL: \(message)")
            exit(1)
        }
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Приложение не может начать работу"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }

    // MARK: Окно выбора файлов для кнопки «Выбрать файлы»

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        if selfTest {
            let samples = Bundle.main.resourceURL!.appendingPathComponent("app/documents")
            let files = (try? FileManager.default.contentsOfDirectory(at: samples, includingPropertiesForKeys: nil)) ?? []
            return completionHandler(files.filter { $0.pathExtension == "txt" })
        }
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.plainText]
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    // MARK: Самопроверка сборки

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard selfTest, webView.url?.host == "127.0.0.1" else { return }
        // Нажимаем «Выбрать файлы» (окно выбора подменяется учебными файлами)
        // и читаем номера договоров из построенной таблицы.
        let script = """
            document.getElementById('fileInput').click();
            await new Promise((resolve) => setTimeout(resolve, 1500));
            return [...document.querySelectorAll('#table tbody tr .num')].map((n) => n.textContent).join(', ');
            """
        webView.callAsyncJavaScript(script, arguments: [:], in: nil, in: .page) { result in
            if case .success(let value) = result, let rows = value as? String, !rows.isEmpty {
                print("SELFTEST OK: окно открыто, выбор файлов работает, в таблице договоры: \(rows)")
                exit(0)
            }
            print("SELFTEST FAIL: таблица не построена (\(result))")
            exit(1)
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
