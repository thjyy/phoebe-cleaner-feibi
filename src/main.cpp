#include <windows.h>
#include <shellapi.h>
#include <propidl.h>
#include <gdiplus.h>
#include <timeapi.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <future>
#include <memory>
#include <random>
#include <string>
#include <thread>
#include <vector>

using namespace Gdiplus;
namespace fs = std::filesystem;

namespace {

constexpr wchar_t kWindowClass[] = L"PhoebeCleanerOverlay";
constexpr wchar_t kSettingsKey[] = L"Software\\PhoebeCleaner";
constexpr int kRenderFps = 60;
constexpr int kEntryDurationMs = 1200;
constexpr int kEatDurationMs = 1400;
constexpr int kSatisfiedDurationMs = 1100;
constexpr int kFailureDurationMs = 1500;
constexpr int kExitDurationMs = 1300;
static_assert(kEntryDurationMs + kEatDurationMs + kSatisfiedDurationMs + kExitDurationMs == 5000);

struct GdiPlusSession {
    ULONG_PTR token{};
    GdiPlusSession() {
        GdiplusStartupInput input;
        GdiplusStartup(&token, &input, nullptr);
    }
    ~GdiPlusSession() { GdiplusShutdown(token); }
};

struct TimerResolutionSession {
    TimerResolutionSession() { timeBeginPeriod(1); }
    ~TimerResolutionSession() { timeEndPeriod(1); }
};

struct Animation {
    std::wstring id;
    std::wstring file;
    int fps;
    int weight;
    int triggerFrame = 0;
};

struct Position {
    int x{};
    int y{};
};

std::wstring ModuleDirectory() {
    std::wstring buffer(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    buffer.resize(length);
    return fs::path(buffer).parent_path().wstring();
}

std::wstring ReadLastChoice(const std::wstring& name) {
    wchar_t buffer[128]{};
    DWORD size = sizeof(buffer);
    if (RegGetValueW(HKEY_CURRENT_USER, kSettingsKey, name.c_str(), RRF_RT_REG_SZ,
                     nullptr, buffer, &size) == ERROR_SUCCESS) {
        return buffer;
    }
    return {};
}

void WriteLastChoice(const std::wstring& name, const std::wstring& value) {
    HKEY key{};
    if (RegCreateKeyExW(HKEY_CURRENT_USER, kSettingsKey, 0, nullptr, 0, KEY_SET_VALUE,
                        nullptr, &key, nullptr) == ERROR_SUCCESS) {
        RegSetValueExW(key, name.c_str(), 0, REG_SZ,
                       reinterpret_cast<const BYTE*>(value.c_str()),
                       static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t)));
        RegCloseKey(key);
    }
}

const Animation& ChooseAnimation(const std::vector<Animation>& pool, const std::wstring& setting) {
    static std::mt19937 generator(std::random_device{}());
    const std::wstring previous = ReadLastChoice(setting);
    std::vector<int> weights;
    weights.reserve(pool.size());
    for (const auto& item : pool) {
        weights.push_back(pool.size() > 1 && item.id == previous ? 0 : item.weight);
    }
    std::discrete_distribution<size_t> distribution(weights.begin(), weights.end());
    const auto& selected = pool[distribution(generator)];
    WriteLastChoice(setting, selected.id);
    return selected;
}

LRESULT CALLBACK WindowProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam) {
    if (message == WM_NCHITTEST) return HTTRANSPARENT;
    if (message == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

bool PumpMessages() {
    MSG message{};
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
        if (message.message == WM_QUIT) return false;
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return true;
}

class Overlay {
public:
    using FrameBuffer = std::vector<std::uint32_t>;

    Overlay(int width, int height) : width_(width), height_(height) {
        WNDCLASSEXW wc{sizeof(wc)};
        wc.lpfnWndProc = WindowProc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.lpszClassName = kWindowClass;
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        RegisterClassExW(&wc);

        hwnd_ = CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST,
            kWindowClass, L"", WS_POPUP, 0, 0, width_, height_, nullptr, nullptr,
            GetModuleHandleW(nullptr), nullptr);
        ShowWindow(hwnd_, SW_SHOWNOACTIVATE);

        screenDc_ = GetDC(nullptr);
        memoryDc_ = CreateCompatibleDC(screenDc_);
        BITMAPINFO info{};
        info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        info.bmiHeader.biWidth = width_;
        info.bmiHeader.biHeight = -height_;
        info.bmiHeader.biPlanes = 1;
        info.bmiHeader.biBitCount = 32;
        info.bmiHeader.biCompression = BI_RGB;
        bitmap_ = CreateDIBSection(memoryDc_, &info, DIB_RGB_COLORS, &pixels_, nullptr, 0);
        oldBitmap_ = SelectObject(memoryDc_, bitmap_);
    }

    ~Overlay() {
        if (oldBitmap_) SelectObject(memoryDc_, oldBitmap_);
        if (bitmap_) DeleteObject(bitmap_);
        if (memoryDc_) DeleteDC(memoryDc_);
        if (screenDc_) ReleaseDC(nullptr, screenDc_);
        if (hwnd_) DestroyWindow(hwnd_);
    }

    std::vector<FrameBuffer> PrepareFrames(Bitmap& sheet) const {
        std::vector<FrameBuffer> frames;
        if (sheet.GetWidth() != static_cast<UINT>(width_ * 5) ||
            sheet.GetHeight() != static_cast<UINT>(height_ * 3)) return frames;

        Rect fullImage(0, 0, static_cast<INT>(sheet.GetWidth()), static_cast<INT>(sheet.GetHeight()));
        BitmapData data{};
        if (sheet.LockBits(&fullImage, ImageLockModeRead, PixelFormat32bppPARGB, &data) != Ok) return frames;
        frames.reserve(15);
        const auto* scan0 = static_cast<const BYTE*>(data.Scan0);
        const int absoluteStride = std::abs(data.Stride);
        for (int frameIndex = 0; frameIndex < 15; ++frameIndex) {
            FrameBuffer buffer(static_cast<size_t>(width_) * height_, 0);
            const int sourceX = (frameIndex % 5) * width_;
            const int sourceY = (frameIndex / 5) * height_;
            auto* destination = reinterpret_cast<BYTE*>(buffer.data());
            for (int row = 0; row < height_; ++row) {
                const int actualY = sourceY + row;
                const BYTE* sourceRow = data.Stride >= 0
                    ? scan0 + static_cast<size_t>(actualY) * data.Stride + sourceX * 4
                    : scan0 + static_cast<size_t>(sheet.GetHeight() - 1 - actualY) * absoluteStride + sourceX * 4;
                std::memcpy(destination + static_cast<size_t>(row) * width_ * 4, sourceRow,
                            static_cast<size_t>(width_) * 4);
            }
            frames.push_back(std::move(buffer));
        }
        sheet.UnlockBits(&data);
        return frames;
    }

    std::vector<FrameBuffer> LoadFrameCache(const fs::path& path) const {
        std::ifstream stream(path, std::ios::binary);
        if (!stream) return {};
        char magic[4]{};
        std::uint32_t version{}, width{}, height{}, count{};
        stream.read(magic, sizeof(magic));
        stream.read(reinterpret_cast<char*>(&version), sizeof(version));
        stream.read(reinterpret_cast<char*>(&width), sizeof(width));
        stream.read(reinterpret_cast<char*>(&height), sizeof(height));
        stream.read(reinterpret_cast<char*>(&count), sizeof(count));
        if (!stream || std::memcmp(magic, "PHFR", 4) != 0 || version != 1 ||
            width != static_cast<std::uint32_t>(width_) || height != static_cast<std::uint32_t>(height_) || count != 15) {
            return {};
        }
        std::vector<FrameBuffer> frames(count, FrameBuffer(static_cast<size_t>(width_) * height_));
        for (auto& frame : frames) {
            stream.read(reinterpret_cast<char*>(frame.data()), static_cast<std::streamsize>(frame.size() * sizeof(std::uint32_t)));
            if (!stream) return {};
        }
        return frames;
    }

    bool DrawFrame(const std::vector<FrameBuffer>& frames, int frameIndex, Position position) {
        std::memcpy(pixels_, frames[frameIndex].data(), static_cast<size_t>(width_) * height_ * 4);

        POINT destination{position.x, position.y};
        SIZE size{width_, height_};
        POINT source{0, 0};
        BLENDFUNCTION blend{AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
        return UpdateLayeredWindow(hwnd_, screenDc_, &destination, &size, memoryDc_, &source,
                                   0, &blend, ULW_ALPHA) != FALSE;
    }

private:
    HWND hwnd_{};
    HDC screenDc_{};
    HDC memoryDc_{};
    HBITMAP bitmap_{};
    HGDIOBJ oldBitmap_{};
    void* pixels_{};
    int width_{};
    int height_{};
};

Position Lerp(Position start, Position end, double amount) {
    amount = std::clamp(amount, 0.0, 1.0);
    amount = amount * amount * (3.0 - 2.0 * amount);
    return {
        static_cast<int>(start.x + (end.x - start.x) * amount),
        static_cast<int>(start.y + (end.y - start.y) * amount)
    };
}

bool DeleteToRecycleBin(const std::wstring& path) {
    std::wstring from = path;
    from.push_back(L'\0');
    from.push_back(L'\0');
    SHFILEOPSTRUCTW operation{};
    operation.wFunc = FO_DELETE;
    operation.pFrom = from.c_str();
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI;
    const int result = SHFileOperationW(&operation);
    return result == 0 && !operation.fAnyOperationsAborted;
}

std::vector<Overlay::FrameBuffer> LoadAnimationFrames(Overlay& overlay, const fs::path& assetRoot,
                                                      const Animation& animation) {
    auto frames = overlay.LoadFrameCache(assetRoot.parent_path() / L"framecache" / (animation.id + L".phfr"));
    if (!frames.empty()) return frames;
    const fs::path path = assetRoot / animation.file;
    Bitmap sheet(path.c_str(), FALSE);
    if (sheet.GetLastStatus() != Ok) return {};
    return overlay.PrepareFrames(sheet);
}

bool PlayAnimation(Overlay& overlay, const std::vector<Overlay::FrameBuffer>& preparedFrames,
                   const Animation& animation, Position start, Position end, int durationMs,
                   const std::function<bool()>& trigger = {}) {
    if (preparedFrames.size() != 15) return false;

    const int renderFrames = std::max(2, (durationMs * kRenderFps) / 1000);
    const bool loopTwice = animation.id == L"entry-run" || animation.id == L"exit-run";
    const double keyFrameRange = loopTwice ? 29.0 : 14.0;
    bool triggerCalled = false;
    const auto stageStart = std::chrono::steady_clock::now();
    for (int renderFrame = 0; renderFrame < renderFrames; ++renderFrame) {
        const double progress = static_cast<double>(renderFrame) / (renderFrames - 1);
        const double keyPosition = progress * keyFrameRange;
        const int spriteFrame = static_cast<int>(keyPosition) % 15;
        if (!triggerCalled && animation.triggerFrame > 0 && keyPosition >= animation.triggerFrame - 1) {
            triggerCalled = true;
            if (trigger && !trigger()) return false;
        }
        overlay.DrawFrame(preparedFrames, spriteFrame, Lerp(start, end, progress));
        if (!PumpMessages()) return false;
        const auto nextFrameTime = stageStart + std::chrono::microseconds(
            static_cast<long long>((renderFrame + 1) * 1000000.0 / kRenderFps));
        std::this_thread::sleep_until(nextFrameTime);
    }
    return true;
}

RECT MonitorWorkArea(POINT point) {
    RECT result{};
    MONITORINFO info{sizeof(info)};
    const HMONITOR monitor = MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST);
    if (GetMonitorInfoW(monitor, &info)) return info.rcWork;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &result, 0);
    return result;
}

Position ClampToWorkArea(Position position, const RECT& work, int width, int height) {
    position.x = std::clamp(position.x, static_cast<int>(work.left), static_cast<int>(work.right - width));
    position.y = std::clamp(position.y, static_cast<int>(work.top), static_cast<int>(work.bottom - height));
    return position;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    int argumentCount = 0;
    std::unique_ptr<wchar_t*, decltype(&LocalFree)> arguments(
        CommandLineToArgvW(GetCommandLineW(), &argumentCount), LocalFree);
    if (!arguments || argumentCount < 2) return 2;

    const std::wstring targetPath = arguments.get()[1];
    if (GetFileAttributesW(targetPath.c_str()) == INVALID_FILE_ATTRIBUTES) return 3;

    SetProcessDPIAware();
    GdiPlusSession gdiplus;
    TimerResolutionSession timerResolution;

    constexpr int overlayWidth = 256;
    constexpr int overlayHeight = 384;
    Overlay overlay(overlayWidth, overlayHeight);

    POINT cursor{};
    GetCursorPos(&cursor);
    const RECT work = MonitorWorkArea(cursor);
    Position target{cursor.x - overlayWidth / 2, cursor.y - overlayHeight * 2 / 3};
    target = ClampToWorkArea(target, work, overlayWidth, overlayHeight);

    const fs::path assetRoot = fs::path(ModuleDirectory()) / L"assets" / L"phoebe" / L"spritesheets_v2";
    const std::vector<Animation> entries{
        {L"entry-run", L"entry-run.png", 10, 55},
        {L"entry-summon", L"entry-summon.png", 10, 25},
        {L"entry-drop", L"entry-drop.png", 10, 20},
    };
    const std::vector<Animation> eats{
        {L"eat-bite", L"eat-bite.png", 9, 55, 11},
        {L"eat-slurp", L"eat-slurp.png", 9, 30, 11},
        {L"eat-toss", L"eat-toss.png", 9, 15, 11},
    };
    const std::vector<Animation> satisfied{
        {L"satisfied-bellypat", L"satisfied-bellypat.png", 10, 60},
        {L"satisfied-hop", L"satisfied-hop.png", 10, 40},
    };
    const std::vector<Animation> exits{
        {L"exit-run", L"exit-run.png", 10, 45},
        {L"exit-sparkle", L"exit-sparkle.png", 10, 35},
        {L"exit-teleport", L"exit-teleport.png", 10, 20},
    };
    const Animation failure{L"failure-bite", L"failure-bite.png", 8, 100};

    const Animation& entry = ChooseAnimation(entries, L"LastEntry");
    const Animation& eat = ChooseAnimation(eats, L"LastEat");
    const Animation& reaction = ChooseAnimation(satisfied, L"LastSatisfied");
    const Animation& exit = ChooseAnimation(exits, L"LastExit");

    auto entryFuture = std::async(std::launch::async, [&] { return LoadAnimationFrames(overlay, assetRoot, entry); });
    auto eatFuture = std::async(std::launch::async, [&] { return LoadAnimationFrames(overlay, assetRoot, eat); });
    auto reactionFuture = std::async(std::launch::async, [&] { return LoadAnimationFrames(overlay, assetRoot, reaction); });
    auto failureFuture = std::async(std::launch::async, [&] { return LoadAnimationFrames(overlay, assetRoot, failure); });
    auto exitFuture = std::async(std::launch::async, [&] { return LoadAnimationFrames(overlay, assetRoot, exit); });

    Position entryStart = target;
    if (entry.id == L"entry-run") {
        const bool enterFromLeft = cursor.x > (work.left + work.right) / 2;
        entryStart.x = enterFromLeft ? target.x - 320 : target.x + 320;
    } else if (entry.id == L"entry-drop") {
        entryStart.y = target.y - 180;
    }
    entryStart = ClampToWorkArea(entryStart, work, overlayWidth, overlayHeight);
    const auto entryFrames = entryFuture.get();
    if (!PlayAnimation(overlay, entryFrames, entry, entryStart, target, kEntryDurationMs)) return 4;

    auto deleteFuture = std::async(std::launch::async, [&] { return DeleteToRecycleBin(targetPath); });
    const auto eatFrames = eatFuture.get();
    const bool eatCompleted = PlayAnimation(overlay, eatFrames, eat, target, target, kEatDurationMs);
    const bool deleteSucceeded = deleteFuture.get();

    if (!eatCompleted || !deleteSucceeded) {
        const auto failureFrames = failureFuture.get();
        PlayAnimation(overlay, failureFrames, failure, target, target, kFailureDurationMs);
    } else {
        const auto reactionFrames = reactionFuture.get();
        PlayAnimation(overlay, reactionFrames, reaction, target, target, kSatisfiedDurationMs);
    }

    Position exitEnd = target;
    if (exit.id == L"exit-run") {
        exitEnd.x = target.x < (work.left + work.right) / 2 ? work.left - overlayWidth : work.right;
    }
    const auto exitFrames = exitFuture.get();
    PlayAnimation(overlay, exitFrames, exit, target, exitEnd, kExitDurationMs);
    return deleteSucceeded ? 0 : 5;
}
