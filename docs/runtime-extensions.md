# 通用会话扩展

工具插件仍使用 register_tool，观察性生命周期使用 register_hook。需要控制原生消息、隔离会话、规范回复或处理真实投递回执的受信任插件，可继承 echo_agent.plugins.runtime.RuntimeExtension，通过 PluginContext.register_runtime_extension 注册。

会话扩展只允许一个所有者，重复或冲突注册会失败。此接口需要 hook.register 权限，在 strict 与 compat 模式下都不允许降级绕过。运行时方法的异常向宿主传播，不能使用观察性 hooks 的 fail-open 行为。独占会话策略的多个项目接入需由同一个扩展协调；普通工具插件可继续并存。原生工具在必需插件成功激活后才按最终策略装配，模型目录也会重新检查策略。

插件通过现有 echo_agent.plugins entry-point 或插件目录安装。通用核心不包含项目实现与项目默认配置。会话扩展必须声明 plugins.required；必需插件缺失、被禁用、未获得注册权限或激活失败均阻止启动，并回收已激活插件资源。

RuntimeExtension 的 validate_config/recover 在注册与接收消息前执行；handle_event/before_turn/presentation 控制消息流程；record_delivery 接收 MessageBus 返回的真实渠道结果。session_scope/memory_namespace/streaming_enabled/system_instructions 是程序拥有的会话策略。allowed_tool_patterns 为独占工具集合，operator tools.deny 始终优先；运行时对象保存在 Config 私有属性中，不序列化到配置或模型上下文。

MCPManager 只调用 bind_mcp_manager、configure_mcp_connection、build_mcp_adapter。插件可返回 None 隐藏私有操作；普通 MCP 在没有扩展时沿用原适配器。register_routes 挂载插件自有认证的 Gateway 端点，宿主不理解端点的项目协议。

插件在受信任 Python 进程内运行，注册权限不是操作系统沙箱。核心不承诺隔离恶意插件；项目权限和业务事务仍应由项目服务检验。
