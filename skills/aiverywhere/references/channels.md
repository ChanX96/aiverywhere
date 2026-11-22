# 外部唤醒与渠道

宿主有定时能力时，由宿主在关闭会话后触发；没有时，下次激活 skill 再继续处理线索。

CLI 可提供常驻 supervisor、Web 和通用 channel worker；WeChat、飞书、iMessage 由桥接器转成统一 envelope。每个入站消息必须带 channel/account/conversation/message_id，回复必须回到原 channel/account/conversation，不能猜测或切换通道。

常驻进程由 `aiverywhere start` 启动、`aiverywhere stop` 停止；不注册系统服务。Web 和 channel worker 在 CLI 退出后继续运行。生成成功、渠道接受和用户实际收到是三个不同事件；缺少送达回执时保留“待核对”，不要声称已送达。

外部操作结果未知时，保留可核实的进度和原因。
