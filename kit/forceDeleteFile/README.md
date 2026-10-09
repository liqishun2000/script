# ForceDelete File

Windows 文件和文件夹强制删除工具。支持：

- 将一个或多个文件、文件夹拖入窗口，或通过“添加文件”“添加文件夹”选择；
- 递归删除文件夹及其子项，目录链接和 junction 仅删除链接本身；
- 先尝试普通永久删除；
- 通过 Windows Restart Manager 显示占用程序；
- 经用户确认后关闭占用程序并重试；
- 仍然失败时，可登记为下次 Windows 启动时删除；
- 在界面中显示逐步日志和每个文件的结果。

## 运行环境

- Windows 10/11
- Python 3.11 或更高版本

安装拖放依赖：

```powershell
cd E:\code\py\kit\forceDeleteFile
python -m pip install -r requirements.txt
```

启动界面：

```powershell
python app.py
```

也可以直接双击 `start_gui.cmd`。

也可以在 `E:\code\py` 下以包方式启动：

```powershell
python -m kit.forceDeleteFile
```

## 命令行测试

```powershell
python cli.py "C:\path\to\locked-file.txt" --schedule-on-reboot
python cli.py "C:\path\to\folder"
```

跳过确认：

```powershell
python cli.py "C:\path\to\locked-file.txt" --yes --schedule-on-reboot
```

## 安全说明

文件夹删除会处理全部子项。子项失败时，父目录显示失败并保留剩余内容；停止操作不会恢复已删除的内容。
选择重启后删除时，按子项到父目录的顺序登记；重启前新写入的内容可能使父目录无法删除。磁盘和共享根目录不能作为删除目标。

删除不经过回收站。关闭占用程序可能导致未保存的数据丢失，因此程序会先显示占用者并要求确认。程序不会尝试关闭 System、Windows 标记的关键进程或自身。删除其他用户、服务或受保护目录中的文件时，可能需要以管理员身份启动终端。
