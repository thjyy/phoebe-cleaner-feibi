#include <windows.h>
#include <exdisp.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <propkey.h>

#include <algorithm>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {

// {7B0EE0AD-A02E-4B17-B55F-389713265BF2}
constexpr CLSID CLSID_PhoebeExplorerCommand = {
    0x7b0ee0ad, 0xa02e, 0x4b17, {0xb5, 0x5f, 0x38, 0x97, 0x13, 0x26, 0x5b, 0xf2}};
constexpr wchar_t kPipeName[] = L"\\\\.\\pipe\\PhoebeCleanerFeibi";
constexpr wchar_t kCommandTitle[] = L"\u53ec\u5524\u83f2\u6bd4\u6765\u6e05\u7406";

HINSTANCE g_module{};
std::atomic<long> g_object_count{};
std::atomic<long> g_lock_count{};

template <typename T>
void SafeRelease(T*& value) {
    if (value) {
        value->Release();
        value = nullptr;
    }
}

std::wstring ModuleDirectory() {
    std::wstring path(32768, L'\0');
    const DWORD length = GetModuleFileNameW(g_module, path.data(), static_cast<DWORD>(path.size()));
    path.resize(length);
    return std::filesystem::path(path).parent_path().wstring();
}

std::string WideToUtf8(const std::wstring& value) {
    if (value.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()),
                                         nullptr, 0, nullptr, nullptr);
    std::string output(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()),
                        output.data(), size, nullptr, nullptr);
    return output;
}

std::string JsonEscape(const std::string& value) {
    std::string output;
    output.reserve(value.size() + 16);
    for (const unsigned char ch : value) {
        switch (ch) {
            case '\\': output += "\\\\"; break;
            case '"': output += "\\\""; break;
            case '\b': output += "\\b"; break;
            case '\f': output += "\\f"; break;
            case '\n': output += "\\n"; break;
            case '\r': output += "\\r"; break;
            case '\t': output += "\\t"; break;
            default:
                if (ch < 0x20) {
                    char buffer[7]{};
                    wsprintfA(buffer, "\\u%04x", ch);
                    output += buffer;
                } else {
                    output.push_back(static_cast<char>(ch));
                }
        }
    }
    return output;
}

std::wstring QuoteArgument(const std::wstring& value) {
    std::wstring result = L"\"";
    size_t backslashes = 0;
    for (const wchar_t ch : value) {
        if (ch == L'\\') {
            ++backslashes;
        } else if (ch == L'"') {
            result.append(backslashes * 2 + 1, L'\\');
            result.push_back(L'"');
            backslashes = 0;
        } else {
            result.append(backslashes, L'\\');
            backslashes = 0;
            result.push_back(ch);
        }
    }
    result.append(backslashes * 2, L'\\');
    result.push_back(L'"');
    return result;
}

void Log(const std::wstring& text) {
    wchar_t local_app_data[MAX_PATH]{};
    if (FAILED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, SHGFP_TYPE_CURRENT, local_app_data))) return;
    const auto directory = std::filesystem::path(local_app_data) / L"PhoebeCleaner";
    std::error_code error;
    std::filesystem::create_directories(directory, error);
    std::wofstream stream(directory / L"bridge.log", std::ios::app);
    if (!stream) return;
    SYSTEMTIME now{};
    GetLocalTime(&now);
    stream << now.wYear << L'-' << now.wMonth << L'-' << now.wDay << L' '
           << now.wHour << L':' << now.wMinute << L':' << now.wSecond << L' ' << text << L'\n';
}

struct ViewPosition {
    bool valid{};
    POINT anchor{};
    HWND explorer_hwnd{};
    HWND view_hwnd{};
    UINT view_mode{};
    POINT spacing{};
};

std::wstring SelectedFilesystemPath(IFolderView* folder_view, PCUITEMID_CHILD child) {
    IPersistFolder2* persist{};
    PIDLIST_ABSOLUTE parent{};
    PIDLIST_ABSOLUTE absolute{};
    wchar_t path[32768]{};
    std::wstring result;
    if (SUCCEEDED(folder_view->GetFolder(IID_PPV_ARGS(&persist))) &&
        SUCCEEDED(persist->GetCurFolder(&parent))) {
        absolute = ILCombine(parent, child);
        if (absolute && SHGetPathFromIDListEx(absolute, path, static_cast<DWORD>(std::size(path)), GPFIDL_DEFAULT)) {
            result = path;
        }
    }
    if (absolute) CoTaskMemFree(absolute);
    if (parent) CoTaskMemFree(parent);
    SafeRelease(persist);
    return result;
}

bool SamePath(const std::wstring& left, const std::wstring& right) {
    if (left.empty() || right.empty()) return false;
    return CompareStringOrdinal(left.c_str(), -1, right.c_str(), -1, TRUE) == CSTR_EQUAL;
}

ViewPosition ResolveFromShellView(IShellView* shell_view, const std::wstring& expected_path = {}) {
    ViewPosition result{};
    if (!shell_view) return result;
    IFolderView* folder_view{};
    ITEMIDLIST* child{};

    HRESULT hr = shell_view->QueryInterface(IID_PPV_ARGS(&folder_view));
    if (FAILED(hr)) {
        std::wostringstream message;
        message << L"resolve QueryInterface(IFolderView) failed hr=0x" << std::hex << static_cast<unsigned long>(hr);
        Log(message.str());
    }
    if (SUCCEEDED(hr)) {
        int selected_index = -1;
        hr = folder_view->GetSelectionMarkedItem(&selected_index);
        if (FAILED(hr) || selected_index < 0) hr = folder_view->GetFocusedItem(&selected_index);
        if (SUCCEEDED(hr) && selected_index >= 0) hr = folder_view->Item(selected_index, &child);
        if (FAILED(hr) || !child) {
            std::wostringstream message;
            message << L"resolve indexed selection failed hr=0x" << std::hex << static_cast<unsigned long>(hr)
                    << L" index=" << std::dec << selected_index;
            Log(message.str());
        }
    }
    if (FAILED(hr) || !child) {
        IEnumIDList* selected{};
        if (SUCCEEDED(folder_view ? folder_view->Items(SVGIO_SELECTION, IID_PPV_ARGS(&selected)) : E_FAIL)) {
            hr = selected->Next(1, &child, nullptr);
        }
        SafeRelease(selected);
    }
    if (SUCCEEDED(hr) && !expected_path.empty() && !SamePath(SelectedFilesystemPath(folder_view, child), expected_path)) {
        Log(L"resolve selected path did not match expected path");
        hr = HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
    }

    if (SUCCEEDED(hr)) {
        hr = shell_view->GetWindow(&result.view_hwnd);
        if (FAILED(hr)) {
            std::wostringstream message;
            message << L"resolve GetWindow failed hr=0x" << std::hex << static_cast<unsigned long>(hr);
            Log(message.str());
        } else {
            result.explorer_hwnd = GetAncestor(result.view_hwnd, GA_ROOT);
        }
    }

    POINT item_position{};
    if (SUCCEEDED(hr)) {
        hr = folder_view->GetItemPosition(child, &item_position);
        if (FAILED(hr)) {
            std::wostringstream message;
            message << L"resolve GetItemPosition failed hr=0x" << std::hex << static_cast<unsigned long>(hr);
            Log(message.str());
        }
    }

    if (SUCCEEDED(hr) && result.view_hwnd) {
        result.spacing = {36, 24};
        folder_view->GetSpacing(&result.spacing);
        folder_view->GetCurrentViewMode(&result.view_mode);

        POINT screen_position = item_position;
        if (ClientToScreen(result.view_hwnd, &screen_position)) {
            const int horizontal_offset = std::clamp(result.spacing.x / 6, 18L, 42L);
            const int vertical_offset = std::clamp(result.spacing.y / 2, 10L, 42L);
            result.anchor = {screen_position.x + horizontal_offset, screen_position.y + vertical_offset};
            result.valid = true;
        }
    }

    if (child) CoTaskMemFree(child);
    SafeRelease(folder_view);
    return result;
}

ViewPosition ResolvePosition(IUnknown* site, const std::wstring& expected_path) {
    if (site) {
        IServiceProvider* provider{};
        IShellBrowser* browser{};
        IShellView* shell_view{};
        HRESULT hr = site->QueryInterface(IID_PPV_ARGS(&provider));
        if (FAILED(hr)) Log(L"resolve site QueryInterface(IServiceProvider) failed");
        if (SUCCEEDED(hr)) hr = provider->QueryService(SID_STopLevelBrowser, IID_PPV_ARGS(&browser));
        if (FAILED(hr)) Log(L"resolve site QueryService(SID_STopLevelBrowser) failed");
        if (SUCCEEDED(hr)) hr = browser->QueryActiveShellView(&shell_view);
        if (FAILED(hr)) Log(L"resolve site QueryActiveShellView failed");
        ViewPosition result = SUCCEEDED(hr) ? ResolveFromShellView(shell_view) : ViewPosition{};
        SafeRelease(shell_view);
        SafeRelease(browser);
        SafeRelease(provider);
        // Modern Details view may return E_NOTIMPL from GetItemPosition.  The
        // exact view HWND is still authoritative and lets the out-of-process
        // Qt runtime obtain the selected row rectangle through UI Automation.
        if (result.valid || result.view_hwnd) return result;
    }

    const HWND foreground = GetForegroundWindow();
    const HWND foreground_root = foreground ? GetAncestor(foreground, GA_ROOTOWNER) : nullptr;
    IShellWindows* windows{};
    if (FAILED(CoCreateInstance(CLSID_ShellWindows, nullptr, CLSCTX_LOCAL_SERVER, IID_PPV_ARGS(&windows)))) {
        return {};
    }

    long count{};
    windows->get_Count(&count);
    ViewPosition fallback{};
    for (long index = 0; index < count; ++index) {
        VARIANT item_index{};
        VariantInit(&item_index);
        V_VT(&item_index) = VT_I4;
        V_I4(&item_index) = index;
        IDispatch* dispatch{};
        IWebBrowserApp* web_browser{};
        IServiceProvider* provider{};
        IShellBrowser* browser{};
        IShellView* shell_view{};
        HWND browser_hwnd{};

        HRESULT hr = windows->Item(item_index, &dispatch);
        if (SUCCEEDED(hr)) hr = dispatch->QueryInterface(IID_PPV_ARGS(&web_browser));
        if (SUCCEEDED(hr)) {
            SHANDLE_PTR raw_hwnd{};
            hr = web_browser->get_HWND(&raw_hwnd);
            browser_hwnd = reinterpret_cast<HWND>(raw_hwnd);
        }
        if (SUCCEEDED(hr)) hr = web_browser->QueryInterface(IID_PPV_ARGS(&provider));
        if (SUCCEEDED(hr)) hr = provider->QueryService(SID_STopLevelBrowser, IID_PPV_ARGS(&browser));
        if (SUCCEEDED(hr)) hr = browser->QueryActiveShellView(&shell_view);

        ViewPosition candidate = SUCCEEDED(hr) ? ResolveFromShellView(shell_view, expected_path) : ViewPosition{};
        if (candidate.valid) {
            candidate.explorer_hwnd = browser_hwnd;
            if (browser_hwnd == foreground || browser_hwnd == foreground_root) {
                fallback = candidate;
                SafeRelease(shell_view);
                SafeRelease(browser);
                SafeRelease(provider);
                SafeRelease(web_browser);
                SafeRelease(dispatch);
                break;
            }
            if (!fallback.valid) fallback = candidate;
        }

        SafeRelease(shell_view);
        SafeRelease(browser);
        SafeRelease(provider);
        SafeRelease(web_browser);
        SafeRelease(dispatch);
    }
    SafeRelease(windows);
    return fallback;
}

std::string BuildRequest(const std::vector<std::wstring>& paths, const ViewPosition& position) {
    std::ostringstream stream;
    stream << "{\"path\":\"" << JsonEscape(WideToUtf8(paths.front())) << "\",\"paths\":[";
    for (size_t index = 0; index < paths.size(); ++index) {
        if (index) stream << ',';
        stream << '\"' << JsonEscape(WideToUtf8(paths[index])) << '\"';
    }
    stream << "],\"x\":" << position.anchor.x << ','
           << "\"y\":" << position.anchor.y << ','
           << "\"position_valid\":" << (position.valid ? "true" : "false") << ','
           << "\"explorer_hwnd\":" << reinterpret_cast<uintptr_t>(position.explorer_hwnd) << ','
           << "\"view_hwnd\":" << reinterpret_cast<uintptr_t>(position.view_hwnd) << ','
           << "\"view_mode\":" << position.view_mode << ','
           << "\"spacing_x\":" << position.spacing.x << ','
           << "\"spacing_y\":" << position.spacing.y << ','
           << "\"source\":\"shell\"}\n";
    return stream.str();
}

bool SendToServer(const std::string& request) {
    if (!WaitNamedPipeW(kPipeName, 40)) return false;
    HANDLE pipe = CreateFileW(kPipeName, GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (pipe == INVALID_HANDLE_VALUE) return false;
    DWORD written{};
    const BOOL okay = WriteFile(pipe, request.data(), static_cast<DWORD>(request.size()), &written, nullptr);
    FlushFileBuffers(pipe);
    CloseHandle(pipe);
    return okay && written == request.size();
}

bool LaunchServer(const std::vector<std::wstring>& paths, const ViewPosition& position) {
    const std::wstring executable = (std::filesystem::path(ModuleDirectory()) / L"PhoebeCleanerQt.exe").wstring();
    if (GetFileAttributesW(executable.c_str()) == INVALID_FILE_ATTRIBUTES) {
        Log(L"animation executable missing: " + executable);
        return false;
    }

    std::wostringstream command;
    command << QuoteArgument(executable) << L" --serve";
    for (const auto& path : paths) command << L" --path " << QuoteArgument(path);
    command << L" --x " << position.anchor.x << L" --y " << position.anchor.y
            << L" --position-valid " << (position.valid ? 1 : 0)
            << L" --explorer-hwnd " << reinterpret_cast<uintptr_t>(position.explorer_hwnd)
            << L" --view-hwnd " << reinterpret_cast<uintptr_t>(position.view_hwnd)
            << L" --view-mode " << position.view_mode;
    std::wstring mutable_command = command.str();
    STARTUPINFOW startup{sizeof(startup)};
    PROCESS_INFORMATION process{};
    const BOOL created = CreateProcessW(executable.c_str(), mutable_command.data(), nullptr, nullptr, FALSE,
                                        CREATE_NO_WINDOW, nullptr, ModuleDirectory().c_str(), &startup, &process);
    if (created) {
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }
    return created != FALSE;
}

class ExplorerCommand final : public IExplorerCommand, public IObjectWithSite {
public:
    ExplorerCommand() { ++g_object_count; }
    ~ExplorerCommand() {
        SafeRelease(site_);
        --g_object_count;
    }

    IFACEMETHODIMP QueryInterface(REFIID iid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (iid == IID_IUnknown || iid == IID_IExplorerCommand) {
            *object = static_cast<IExplorerCommand*>(this);
        } else if (iid == IID_IObjectWithSite) {
            *object = static_cast<IObjectWithSite*>(this);
        } else {
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }

    IFACEMETHODIMP_(ULONG) AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&references_)); }
    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&references_));
        if (!remaining) delete this;
        return remaining;
    }

    IFACEMETHODIMP GetTitle(IShellItemArray*, LPWSTR* title) override {
        if (!title) return E_POINTER;
        return SHStrDupW(kCommandTitle, title);
    }
    IFACEMETHODIMP GetIcon(IShellItemArray*, LPWSTR* icon) override {
        if (!icon) return E_POINTER;
        const std::wstring path = (std::filesystem::path(ModuleDirectory()) / L"PhoebeCleanerQt.exe").wstring();
        return SHStrDupW(path.c_str(), icon);
    }
    IFACEMETHODIMP GetToolTip(IShellItemArray*, LPWSTR* text) override {
        if (!text) return E_POINTER;
        return SHStrDupW(L"\u8ba9\u83f2\u6bd4\u628a\u8fd9\u4e2a\u6587\u4ef6\u5403\u6389", text);
    }
    IFACEMETHODIMP GetCanonicalName(GUID* guid) override {
        if (!guid) return E_POINTER;
        *guid = CLSID_PhoebeExplorerCommand;
        return S_OK;
    }
    IFACEMETHODIMP GetState(IShellItemArray* items, BOOL, EXPCMDSTATE* state) override {
        if (!state) return E_POINTER;
        DWORD count{};
        *state = items && SUCCEEDED(items->GetCount(&count)) && count >= 1 && count <= 20
                     ? ECS_ENABLED
                     : ECS_DISABLED;
        return S_OK;
    }
    IFACEMETHODIMP Invoke(IShellItemArray* items, IBindCtx*) override {
        if (!items) return E_INVALIDARG;
        DWORD count{};
        HRESULT hr = items->GetCount(&count);
        if (FAILED(hr) || count == 0 || count > 20) return E_INVALIDARG;
        std::vector<std::wstring> paths;
        paths.reserve(count);
        for (DWORD index = 0; index < count; ++index) {
            IShellItem* item{};
            PWSTR raw_path{};
            hr = items->GetItemAt(index, &item);
            if (SUCCEEDED(hr)) hr = item->GetDisplayName(SIGDN_FILESYSPATH, &raw_path);
            if (FAILED(hr) || !raw_path) {
                SafeRelease(item);
                if (raw_path) CoTaskMemFree(raw_path);
                return FAILED(hr) ? hr : E_FAIL;
            }
            paths.emplace_back(raw_path);
            CoTaskMemFree(raw_path);
            SafeRelease(item);
        }

        const ViewPosition position = ResolvePosition(site_, paths.front());
        const std::string request = BuildRequest(paths, position);
        const bool sent = SendToServer(request);
        const bool launched = sent || LaunchServer(paths, position);

        std::wostringstream diagnostic;
        diagnostic << L"invoke path=" << paths.front() << L" count=" << paths.size()
                   << L" site=" << (site_ != nullptr) << L" valid=" << position.valid
                   << L" anchor=" << position.anchor.x << L',' << position.anchor.y
                   << L" view=" << reinterpret_cast<uintptr_t>(position.view_hwnd)
                   << L" mode=" << position.view_mode << L" spacing=" << position.spacing.x << L'x' << position.spacing.y
                   << (sent ? L" ipc=sent" : launched ? L" ipc=launched" : L" ipc=failed");
        Log(diagnostic.str());
        return launched ? S_OK : E_FAIL;
    }
    IFACEMETHODIMP GetFlags(EXPCMDFLAGS* flags) override {
        if (!flags) return E_POINTER;
        *flags = ECF_DEFAULT;
        return S_OK;
    }
    IFACEMETHODIMP EnumSubCommands(IEnumExplorerCommand**) override { return E_NOTIMPL; }

    IFACEMETHODIMP SetSite(IUnknown* site) override {
        if (site) site->AddRef();
        SafeRelease(site_);
        site_ = site;
        return S_OK;
    }
    IFACEMETHODIMP GetSite(REFIID iid, void** site) override {
        if (!site) return E_POINTER;
        *site = nullptr;
        return site_ ? site_->QueryInterface(iid, site) : E_FAIL;
    }

private:
    long references_{1};
    IUnknown* site_{};
};

class ClassFactory final : public IClassFactory {
public:
    IFACEMETHODIMP QueryInterface(REFIID iid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (iid != IID_IUnknown && iid != IID_IClassFactory) return E_NOINTERFACE;
        *object = static_cast<IClassFactory*>(this);
        AddRef();
        return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return static_cast<ULONG>(InterlockedIncrement(&references_)); }
    IFACEMETHODIMP_(ULONG) Release() override {
        const ULONG remaining = static_cast<ULONG>(InterlockedDecrement(&references_));
        if (!remaining) delete this;
        return remaining;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** object) override {
        if (outer) return CLASS_E_NOAGGREGATION;
        auto* command = new (std::nothrow) ExplorerCommand();
        if (!command) return E_OUTOFMEMORY;
        const HRESULT hr = command->QueryInterface(iid, object);
        command->Release();
        return hr;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        lock ? ++g_lock_count : --g_lock_count;
        return S_OK;
    }
private:
    long references_{1};
};

}  // namespace

extern "C" __declspec(dllexport) HRESULT WINAPI DllGetClassObject(REFCLSID clsid, REFIID iid, void** object) {
    if (clsid != CLSID_PhoebeExplorerCommand) return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) ClassFactory();
    if (!factory) return E_OUTOFMEMORY;
    const HRESULT hr = factory->QueryInterface(iid, object);
    factory->Release();
    return hr;
}

extern "C" __declspec(dllexport) HRESULT WINAPI DllCanUnloadNow() {
    return g_object_count == 0 && g_lock_count == 0 ? S_OK : S_FALSE;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
