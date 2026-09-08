"""packages/tools：消费方工具（往 ctx.tools 注册表写工具的 module 插件）。

bash / read_file 是「消费方工具插件」（有 name/inject/apply，进清单激活）。
技能 catalog、委派 task 是所在 service 的辅助工厂，留在各自 service 内，不在此。
"""
