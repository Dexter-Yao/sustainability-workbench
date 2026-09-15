// ABOUTME: 工作台输入说明图标：Hint 原语（design.md §2.8.1）的业务薄包装，按模板提供的
// ABOUTME: 用户可见帮助文本展开；未配置说明时不渲染任何交互元素。
"use client";

import { Hint } from "@/components/ui/Hint";

export function InputGuidance({ helpText }: { helpText?: string | null }) {
  if (!helpText) return null;
  return <Hint content={helpText} style={{ marginLeft: 5 }} />;
}
