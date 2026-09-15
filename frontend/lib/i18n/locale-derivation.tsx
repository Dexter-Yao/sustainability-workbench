// ABOUTME: 界面语言的默认值派生：跟随当前报告所属知识包的语言，用户显式选过后不再改写。
// ABOUTME(en): Derives the default UI locale from the active report's package; a user's explicit choice wins.
// ABOUTME: 独立成组件是因为 LocaleProvider 在 AppProvider 之外（登录页也要取词），
// ABOUTME: 拿不到报告；把派生放在报告上下文内部，避免为此倒置 Provider 顺序。
"use client";

import { useEffect } from "react";

import { useApp } from "../app-context";
import { uiLocaleForPackage } from "./locale";
import { useLocale } from "./locale-context";

export function LocaleDerivation() {
  const { report } = useApp();
  const { adoptDerived } = useLocale();
  const knowledgePackageId = report?.knowledgePackageId ?? null;

  useEffect(() => {
    adoptDerived(uiLocaleForPackage(knowledgePackageId));
  }, [knowledgePackageId, adoptDerived]);

  return null;
}
