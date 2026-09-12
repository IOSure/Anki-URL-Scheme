# Anki URL Scheme 对话与开发总结

## 1. 项目背景

项目原目录名为 `anki-links`，现已重命名为：

```text
/Users/reixu/Documents/Projects/Anki-URL-Scheme
```

项目目标是为 Anki 提供 `anki://` URL 处理能力，使浏览器、Obsidian 或其他应用可以调用 Anki 的搜索、牌组选择等功能。

本次主要解决插件在以下环境中的兼容性问题：

- Anki `25.09.5 (217701ba)`
- Python `3.13.5`
- Qt `6.9.1`
- Chromium `122`

## 2. 原始问题

用户反馈插件已经无法支持新版 Anki。

经过检查，问题不只是一处 API 变化，而是涉及多个层面：

1. 插件依赖 `ankiutils`，但实际安装目录没有对应的 `vendor/ankiutils`。
2. macOS 协议注册依赖 PyObjC，但新版 Anki 环境没有 `Foundation` 和 `LaunchServices`。
3. Anki 的 `appMsg` 信号连接时机与旧实现不完全兼容。
4. 旧浏览器搜索和牌组选择方式不再适合当前 Anki API。
5. Anki 25.09 的应用包不再声明 `anki` URL scheme。
6. Anki 已运行时，旧的 `open -b` 命令不能把 URL 参数传给现有实例。
7. 第三方工具生成的 `anki://x-callback-url/search?query=...` 链接不被原插件支持。

## 3. 代码修改总结

### 3.1 URL 解析

新增 `src/url_utils.py`：

- 统一处理 `anki://`、`anki:`、Windows 反斜杠和带引号 URL。
- 分别解析 URL path 和 query。
- 支持 `search` 和 `deck` 命令。
- 新增 x-callback-url 支持：

  ```text
  anki://x-callback-url/search?query=cid%3A1692469068390
  ```

  会转换为内部搜索：

  ```text
  cid:1692469068390
  ```

### 3.2 Anki 事件 Hook

修改 `src/hooks.py`：

- 兼容 `appMsg` 信号已连接和尚未连接两种情况。
- 已连接时先断开旧槽函数，再连接 URL 包装器。
- 未连接时只替换 `mw.onAppMsg`，等待 Anki 后续连接。
- 非 `anki://` 参数继续交给 Anki 原生逻辑。
- macOS 下继续处理 `QFileOpenEvent`。

### 3.3 命令执行

修改 `src/handler.py`：

- 继续使用后台队列处理 URL。
- 等待 `mw.col` 加载完成后再执行命令。
- 浏览器搜索改用：

  ```python
  aqt.dialogs.open("Browser", mw, search=(search_query,))
  ```

- 牌组选择改用 `create=False`，避免 URL 指向不存在的牌组时自动创建牌组。

### 3.4 移除旧依赖

修改 `src/config.py`、`src/consts.py`、`src/log.py`、`src/main.py` 和 requirements 文件：

- 删除 `ankiutils`。
- 删除 PyObjC 运行时依赖。
- 日志改用 Anki 原生 add-on logger：

  ```python
  logging.getLogger("addon.anki_links")
  ```

- 配置和常量改用标准库实现。

### 3.5 macOS URL 转发器

修改 `src/protocol.py`，新增 macOS URL 转发 App：

```text
<addon>/user_files/Anki URL Handler.app
```

原因：

- Anki 25.09 的 `Info.plist` 不再声明 `anki` scheme。
- 不能可靠地直接把 Anki 自身设置为 URL handler。

处理方式：

1. 使用 `osacompile` 生成 AppleScript App。
2. 写入 `CFBundleURLTypes` 声明 `anki` scheme。
3. 使用 ad-hoc `codesign` 签名。
4. 使用 `lsregister` 注册 App。
5. 优先使用 macOS `NSWorkspace` 现代 API 设置默认处理器。
6. 失败时回退旧 `LSSetDefaultHandlerForURLScheme`。
7. 转发时使用：

   ```bash
   open -n -b net.ankiweb.launcher --args "<anki URL>"
   ```

`-n` 很关键，它会启动新的 Anki 参数进程，再由 Anki 单实例机制把 URL 转发给主实例。

### 3.6 测试与文档

- 用 `tests/test_url_utils.py` 替换占位测试。
- 覆盖标准命令、Windows URL、编码字符、非法 URL 和 x-callback-url。
- 更新 `README.md`。
- 更新 `CHANGELOG.md`。
- 新增 `ANKI_25.09_COMPATIBILITY.md` 技术总结。
- 新增部署辅助脚本 `anki-url-scheme.sh`。

## 4. 开发思路

开发过程采用分层排查方式：

1. 检查 Anki 25.09.5 的真实 Python 运行环境。
2. 确认有哪些模块导入会直接失败。
3. 对照新版 Anki 源码检查：
   - 启动顺序
   - `appMsg` 信号
   - Browser API
   - Deck API
   - macOS `QFileOpenEvent`
4. 将 URL 解析抽成纯函数，方便独立验证。
5. 分别验证：
   - 插件加载
   - URL 解析
   - Anki 事件接收
   - macOS URL 分配
   - Anki 单实例转发
6. 使用隔离 Anki Base 做测试，避免影响真实牌组。

## 5. 遇到的问题与解决方法

| 问题 | 原因 | 解决方法 |
| --- | --- | --- |
| `No module named ankiutils` | 安装包没有 vendor 依赖 | 删除 `ankiutils`，改用标准库 |
| PyObjC 缺失 | 新版 Anki 环境未安装 PyObjC | 使用 `ctypes` 和 JXA |
| 信号 Hook 失效 | 不同启动阶段连接状态不同 | 安全断开和重连，或延迟绑定 |
| Browser API 变化 | 旧控件访问方式不稳定 | 改用 `dialogs.open(..., search=...)` |
| 不存在的牌组被创建 | `decks.id()` 默认 `create=True` | 改为 `create=False` |
| macOS 无 `anki` scheme | Anki Info.plist 不再声明 | 创建独立 URL 转发 App |
| 已运行 Anki 收不到 URL | `open -b` 只激活应用 | 使用 `open -n -b` |
| x-callback-url 被拒绝 | 解析器只支持一级命令 | 增加 action 和 query 参数解析 |
| 测试进程未退出 | GUI 进程忽略普通终止信号 | 使用隔离环境并在验证后强制清理 |
| CLI 无法编译 AppleScript | 沙箱限制 XPC 和 StandardAdditions | 在真实运行环境中验证 |

## 6. 验证结果

已完成的验证：

- Python 源码编译通过。
- URL 解析断言通过。
- Anki 25.09.5 隔离环境启动无插件加载错误。
- macOS URL 转发 App 已成功生成并注册。
- 真实执行：

  ```bash
  open "anki://deck/__anki_links_verification_missing__"
  ```

  插件日志出现：

  ```text
  INFO:addon.anki_links: Handling deck URL with 1 path component(s)
  ```

- x-callback-url 解析已通过验证。

## 7. 目录重命名

项目目录已从：

```text
/Users/reixu/Documents/Projects/anki-links
```

修改为：

```text
/Users/reixu/Documents/Projects/Anki-URL-Scheme
```

同时更新了：

- `anki-url-scheme.sh` 中的项目路径。
- `ANKI_25.09_COMPATIBILITY.md` 中的项目路径和缓存路径。

## 8. GitHub 提交与推送

目标仓库：

```text
https://github.com/IOSure/Anki-URL-Scheme
```

本地 Git 配置：

- `origin` 已改为 SSH：

  ```text
  git@github.com:IOSure/Anki-URL-Scheme.git
  ```

- 原上游保留为：

  ```text
  upstream -> https://github.com/abdnh/anki-links.git
  ```

提交信息：

```text
574bbe6 Support Anki 25.09 and x-callback URLs
```

推送结果：

```text
d372e26..574bbe6  main -> main
```

远端 `main` 已确认指向：

```text
574bbe6d55390b9bbf62247f561dc31586ae46a5
```

## 9. 认证问题

第一次尝试 HTTPS 推送时，GitHub 拒绝账户密码：

```text
Password authentication is not supported for Git operations.
```

解决方法：

- 本机已有 `~/.ssh/id_rsa`。
- SSH key 已添加到 GitHub。
- 测试结果：

  ```text
  Hi IOSure! You've successfully authenticated
  ```

- 将 `origin` 切换到 SSH 后推送成功。

以后提交后只需要：

```bash
git push
```

不会再要求输入 GitHub 密码。

## 10. 当前状态

- 项目兼容性修复已完成。
- 项目目录已重命名。
- Git 提交已创建。
- 代码已推送到 GitHub。
- 本地 `main` 已跟踪 `origin/main`。
- 工作区没有未提交的代码修改。

