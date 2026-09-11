# Anki Links 25.09 兼容性修复总结

## 1. 项目概述

Anki Links 是一个 Anki 插件，用于注册并处理 `anki://` 自定义 URL，从浏览器、Obsidian 或其他应用向 Anki 发送命令。

当前支持的主要命令包括：

- 打开浏览器并执行搜索：`anki://search/<query>`
- 选择指定牌组：`anki://deck/<deck name>`
- x-callback-url 搜索：`anki://x-callback-url/search?query=<query>`

本次适配目标环境：

- Anki `25.09.5 (217701ba)`
- Python `3.13.5`
- Qt `6.9.1`
- Chromium `122`

## 2. 原始问题

插件在 Anki 25.09 下无法正常使用，主要涉及以下几类问题：

1. 插件依赖旧的 `ankiutils`，但安装目录中不存在对应的 `vendor/ankiutils`。
2. macOS 协议注册依赖 PyObjC，但新版 Anki 运行环境不再提供 `Foundation` 和 `LaunchServices`。
3. Anki 25.09 的窗口信号连接顺序和旧版本行为不同，原有 Hook 逻辑需要兼容不同连接状态。
4. 浏览器搜索和牌组选择使用了旧实现方式，需要切换到当前 Anki API。
5. 新版 Anki 的 `Info.plist` 不再声明 `anki` URL scheme，单纯调用旧 LaunchServices API 无法可靠注册 URL 处理器。
6. 现有 Obsidian/第三方插件生成的链接格式是：

   ```text
   anki://x-callback-url/search?query=cid:...
   ```

   原插件只支持 `anki://search/...`，会报 `Invalid command: x-callback-url`。

## 3. 修改内容

### 3.1 URL 解析

新增 `src/url_utils.py`，统一处理不同平台和不同来源的 URL。

主要能力：

- 兼容 `anki://...`、`anki:...` 以及 Windows 双反斜杠形式。
- 去除 URL 两侧引号。
- 统一反斜杠和正斜杠。
- 分别解码 URL path 和 query，避免提前解码破坏参数结构。
- 支持标准命令：

  ```text
  anki://search/tag%3Afoo
  anki://deck/Default
  ```

- 支持 x-callback-url：

  ```text
  anki://x-callback-url/search?query=cid%3A1692469068390
  ```

  该链接最终会转换为内部 `search` 命令，查询内容为：

  ```text
  cid:1692469068390
  ```

### 3.2 Anki 事件 Hook

修改 `src/hooks.py`：

- 在 Anki 的 `appMsg` 信号连接前或连接后都能安全安装包装逻辑。
- 如果信号已经连接到 `mw.onAppMsg`，先断开旧连接，再连接到新的 URL 处理包装器。
- 如果信号尚未连接，只替换方法，让 Anki 后续连接时自动使用包装器。
- 保留非 `anki://` 参数给 Anki 原有导入逻辑。
- macOS 下继续安装 `QFileOpenEvent` 过滤器，处理运行时传入的 URL。
- 忽略没有有效 `anki` scheme 的普通文件打开事件。

### 3.3 命令处理

修改 `src/handler.py`：

- 使用 `parse_anki_url()` 统一解析并校验命令。
- 保持后台线程和命令队列，确保 Anki 启动或加载资料时收到的命令不会丢失。
- 等待 `mw.col` 可用后再执行命令。
- 搜索改用当前 Anki 支持的方式：

  ```python
  aqt.dialogs.open("Browser", mw, search=(search_query,))
  ```

- 牌组选择改用：

  ```python
  mw.col.decks.id(deck_name, create=False)
  ```

  避免 URL 指向不存在的牌组时意外创建新牌组。
- 继续通过 `mw.taskman.run_on_main()` 回到主线程操作 UI。

### 3.4 移除旧运行时依赖

修改以下文件，移除 `ankiutils` 和 PyObjC 依赖：

- `src/config.py`
- `src/consts.py`
- `src/log.py`
- `src/main.py`
- `requirements/bundle.in`
- `requirements/bundle.txt`

处理方式：

- 插件名改为代码内常量。
- 配置暂为空字典，不依赖旧配置封装。
- 日志直接使用：

  ```python
  logging.getLogger("addon.anki_links")
  ```

  Anki 会自动把该前缀的日志写入插件日志文件。
- 删除 `vendor` 路径注入，因为不再需要随插件打包第三方运行库。

### 3.5 macOS URL 协议注册

修改 `src/protocol.py`，这是本次改动最大的部分。

新版 Anki 的应用包：

```text
/Applications/Anki.app/Contents/Info.plist
```

不再声明 `anki` URL scheme，因此不能直接把 Anki 自身注册为 handler。

新的处理方案是生成一个轻量 URL 转发器：

```text
<addon>/user_files/Anki URL Handler.app
```

该 App：

1. 在 `Info.plist` 中声明 `anki` scheme。
2. 接收 macOS 的 URL AppleEvent。
3. 调用：

   ```bash
   /usr/bin/open -n -b net.ankiweb.launcher --args "<anki URL>"
   ```

4. 通过 Anki 的单实例参数通道把 URL 发送给正在运行的 Anki。

注册流程：

- 使用 `osacompile` 生成 AppleScript App。
- 修改 `Info.plist`：
  - `CFBundleIdentifier`
  - `CFBundleURLTypes`
  - `LSUIElement`
- 使用 ad-hoc 签名：

  ```bash
  codesign --force --deep --sign -
  ```

- 使用 `lsregister -f` 向 LaunchServices 注册 App。
- 优先通过 macOS 现代 API 设置默认处理器：

  ```text
  NSWorkspace.setDefaultApplicationAtURL:toOpenURLsWithScheme:completionHandler:
  ```

- 如果现代 API 不可用，再回退到旧 `LSSetDefaultHandlerForURLScheme`。

### 3.6 测试

将原占位测试 `tests/test_example.py` 替换为 `tests/test_url_utils.py`。

覆盖内容：

- 标准搜索 URL。
- 标准牌组 URL。
- Windows 反斜杠 URL。
- 带引号的 URL。
- `%3A`、`%2F` 等编码。
- x-callback-url 搜索格式。
- 非法命令和缺少参数的 URL。

### 3.7 文档

- `README.md` 增加 Anki 25.09.5 测试环境说明。
- `CHANGELOG.md` 增加兼容性修复记录。

## 4. 开发思路

本次没有只针对报错做局部替换，而是按“启动、解析、事件、执行、系统注册”分层排查。

### 4.1 使用真实运行环境作为依据

本机 Anki 25.09.5 使用的是独立 Python 环境：

```text
~/Library/Application Support/AnkiProgramFiles/.venv
```

开发过程中直接检查了该环境中的 Anki 源码，而不是根据旧版 API 猜测。

重点确认：

- `aqt.main.AnkiQt` 的启动顺序。
- `appMsg` 信号的连接时机。
- `aqt.dialogs.open("Browser", ..., search=...)` 的当前签名。
- `mw.col.decks.id(..., create=False)` 的当前行为。
- `AnkiApp.event()` 对 `QFileOpenEvent` 的处理方式。

### 4.2 先隔离问题层级

问题被拆分为：

1. Python 模块导入失败。
2. Anki 插件启动失败。
3. URL 解析失败。
4. Anki 信号未进入插件。
5. macOS 未把 URL 分配给插件。
6. Anki 已运行时 URL 没有进入单实例通道。

每一层分别验证，避免把“系统未注册”误判成“插件没有处理”。

### 4.3 保留向后兼容

- 旧格式 `anki://search/...` 和 `anki://deck/...` 继续可用。
- 新增 `x-callback-url` 格式，不替换原格式。
- macOS 优先使用现代 API，失败时回退旧 API。
- 非 `anki://` 参数继续交给 Anki 原有逻辑。

### 4.4 尽量避免外部依赖

原实现依赖 `ankiutils` 和 PyObjC，容易受 Anki 内嵌 Python 环境影响。

修复后：

- 运行时无第三方 Python 包依赖。
- macOS 使用系统自带：
  - `osacompile`
  - `codesign`
  - `osascript`
  - `ctypes`
- 插件仍只依赖 Anki 自身提供的 `aqt` 和 `anki` 模块。

## 5. 遇到的问题与解决方法

### 5.1 `No module named ankiutils`

原因：

- 插件源码依赖 `ankiutils`。
- 实际安装目录没有 `vendor/ankiutils`。

解决：

- 移除 `ankiutils`。
- 配置、常量和日志改为标准库或 Anki 原生日志实现。

### 5.2 PyObjC 缺失

原因：

- 旧 macOS 注册逻辑依赖 `Foundation` 和 `LaunchServices`。
- Anki 25.09.5 的 Python 环境没有 PyObjC。

解决：

- 使用 `ctypes` 调用 CoreServices 作为旧 API 回退。
- 使用 JXA/ObjC bridge 调用现代 `NSWorkspace` API。
- 不再依赖 PyObjC。

### 5.3 `appMsg` 信号连接顺序

原因：

- 不同版本或启动阶段中，`mw.onAppMsg` 可能已经连接或尚未连接。
- 无条件 `disconnect()` 会导致异常；只替换方法又可能错过已存在的信号连接。

解决：

- 尝试安全断开。
- 如果成功，断开后重新连接包装器。
- 如果尚未连接，只替换方法，等待 Anki 后续连接。

### 5.4 旧浏览器 API 不适用

原因：

- 旧代码直接操作 Browser 的搜索控件。
- 新版 Anki 内部控件和方法不能继续作为稳定接口使用。

解决：

- 改用公开的 dialog API，通过 `search=` 参数打开或复用浏览器。

### 5.5 不存在的牌组被自动创建

原因：

- 旧代码调用 `decks.id(deck_name)`，默认 `create=True`。

解决：

- 改为 `create=False`。
- 找不到牌组时记录错误，不修改用户牌组集合。

### 5.6 Anki 25.09 不再声明 `anki` scheme

原因：

- Anki App 的 `Info.plist` 没有 `CFBundleURLTypes`。
- 直接设置 Anki 为 URL handler 不可靠。

解决：

- 生成独立的 `Anki URL Handler.app`。
- 由转发器声明 scheme，再调用 Anki。
- 转发器存放在插件的 `user_files`，插件升级时可保留。

### 5.7 `open -b` 无法把 URL 传给已运行的 Anki

原因：

- Anki 已运行时，`open -b bundle-id --args URL` 通常只激活现有应用。
- 不会再启动携带参数的第二进程。

解决：

- 改为：

  ```bash
  open -n -b net.ankiweb.launcher --args "<anki URL>"
  ```

- `-n` 会启动新的进程，再由 Anki 单实例逻辑把参数转发给主实例。

### 5.8 原有链接使用 x-callback-url

原因：

- 第三方插件生成：

  ```text
  anki://x-callback-url/search?query=cid:...
  ```

- 原解析器只认可 `search` 和 `deck` 作为第一段命令。

解决：

- 识别 `x-callback-url/<action>`。
- 解析 `query` 参数。
- 将 `search` 和 `deck` action 转换为内部命令。

### 5.9 沙箱环境导致 `osacompile` 误报

原因：

- 测试命令在受限沙箱中运行时，AppleScript 编译可能因 XPC/StandardAdditions 权限而失败。
- 实际 Anki 和 LaunchServices 运行时不受该沙箱限制。

解决：

- 在真实终端/受控环境中重新验证 App 编译。
- 将沙箱错误与插件真实运行错误区分开。

## 6. 验证结果

已完成以下验证：

1. Python 源码编译通过：

   ```bash
   PYTHONPYCACHEPREFIX=/tmp/anki-url-scheme-pycache \
     python3 -m compileall -q src tests
   ```

2. URL 解析断言通过，包括：

   ```text
   anki://search/tag%3Afoo
   anki://deck/Default
   anki://x-callback-url/search?query=cid%3A1692469068390
   ```

3. 在隔离 Anki Base 中启动 Anki 25.09.5，插件无加载异常。

4. 实际安装目录中的 `protocol.py` 和 `url_utils.py` 已通过独立加载验证。

5. macOS 已生成并注册：

   ```text
   ~/Library/Application Support/Anki2/addons21/anki_links/user_files/Anki URL Handler.app
   ```

6. 实际测试：

   ```bash
   open "anki://deck/__anki_links_verification_missing__"
   ```

   插件日志出现：

   ```text
   INFO:addon.anki_links: Handling deck URL with 1 path component(s)
   ```

   证明以下链路已打通：

   ```text
   macOS URL scheme
     -> Anki URL Handler.app
     -> Anki 单实例
     -> 插件 appMsg Hook
     -> URL 解析
     -> 命令队列
   ```

7. 当前环境未安装 `pytest`，因此没有直接执行 `pytest`；已使用等价的 Python 断言完成解析验证。

## 7. 部署方式

将源码同步到本机 Anki 插件目录：

```bash
cd /Users/reixu/Documents/Projects/Anki-URL-Scheme

rsync -a \
  --exclude __pycache__ \
  --exclude config.json \
  --exclude user_files/ \
  src/ "$HOME/Library/Application Support/Anki2/addons21/anki_links/"
```

然后：

1. 完全退出并重新启动 Anki。
2. 打开：

   ```text
   Tools -> Anki Links -> Register protocol handler
   ```

3. 测试搜索链接：

   ```bash
   open "anki://x-callback-url/search?query=cid%3A1692469068390"
   ```

4. 测试牌组链接：

   ```bash
   open "anki://deck/Default"
   ```

如果只是本机开发，使用 `rsync` 部署即可，不需要打包。

如果需要生成可分发插件包：

```bash
make ankiweb
```

## 8. 文件修改清单

| 文件 | 修改内容 |
| --- | --- |
| `src/url_utils.py` | 新增统一 URL 规范化、解析和 x-callback-url 支持 |
| `src/hooks.py` | 重写 Anki URL Hook 和 macOS `QFileOpenEvent` 处理 |
| `src/handler.py` | 更新命令队列、浏览器搜索和牌组选择 API |
| `src/protocol.py` | 新增 macOS URL 转发器、现代 API 注册和旧 API 回退 |
| `src/main.py` | 移除 `vendor` 依赖，简化初始化 |
| `src/config.py` | 移除 `ankiutils` 配置依赖 |
| `src/consts.py` | 使用内置常量替代 `ankiutils` |
| `src/log.py` | 使用 Anki 原生 add-on logger 前缀 |
| `requirements/bundle.in` | 删除运行时依赖 |
| `requirements/bundle.txt` | 删除锁定的 `ankiutils` 和 PyObjC 依赖 |
| `tests/test_url_utils.py` | 替换占位测试，覆盖 URL 解析场景 |
| `README.md` | 补充支持环境说明 |
| `CHANGELOG.md` | 记录兼容性修复 |

## 9. 已知限制

- Windows 和 Linux 的协议注册代码已保留，但本次只在 macOS 上进行了完整运行验证。
- macOS 的 URL 转发器依赖系统自带的 `osacompile`、`codesign` 和 `osascript`。
- macOS 26 已弃用部分旧 LaunchServices API，旧接口仅作为回退。
- `x-callback-url` 当前只映射 `search` 和 `deck`，不是完整的通用 x-callback-url 实现。
- 修改后的插件代码只有在 Anki 完全重启后才会生效。
