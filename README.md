# Phoebe Cleaner / 菲比清理器

Windows 文件资源管理器右键菜单小工具。选择“召唤菲比来清理”后，菲比会播放出现、接近、吃掉文件、满足和退场动画，并将目标移入回收站。

## 当前版本

- 原生 Win32 C++ / GDI+ 透明分层窗口
- 多套出现、进食、满足和退场动画随机组合
- 动画流程约 5 秒
- 支持普通文件和文件夹
- Windows 11 菜单位于“显示更多选项”中

## 使用

仓库中的 `dist` 目录包含当前构建。运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

卸载右键菜单：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

## 构建

需要 CMake、Ninja，以及支持 C++20 的 MinGW-w64 GCC：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

动画源素材和运行时精灵图位于 `assets/phoebe`。

