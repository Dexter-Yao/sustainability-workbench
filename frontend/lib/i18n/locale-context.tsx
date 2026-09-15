// ABOUTME: 界面语言上下文：持有语言与取词字典，挂在 Provider 链最外层（登录页也要取词）。
// ABOUTME(en): UI locale context holding the active locale and its dictionary; mounted outermost.
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import type { Dictionary } from "./dictionary";
import { en } from "./en";
import { htmlLang, type UiLocale } from "./locale";
import {
  LOCALE_DATASET_ATTRIBUTE,
  resolveInitialLocale,
  writeStoredLocale,
  type LocaleSource,
} from "./locale-storage";
import { zhHans } from "./zh-Hans";

const DICTIONARIES: Record<UiLocale, Dictionary> = { "zh-Hans": zhHans, en };

interface LocaleContextValue {
  locale: UiLocale;
  source: LocaleSource;
  /** 用户显式选择：此后任何报告都不再改写界面语言。 */
  selectLocale: (locale: UiLocale) => void;
  /** 报告语言派生的默认值；用户显式选过后是 no-op。 */
  adoptDerived: (locale: UiLocale) => void;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: "zh-Hans",
  source: "derived",
  selectLocale: () => {},
  adoptDerived: () => {},
});

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  // 初值取自首帧脚本写在根元素上的属性，保证与已经画出的那一帧一致。
  const [state, setState] = useState(() => resolveInitialLocale());

  useEffect(() => {
    document.documentElement.setAttribute(LOCALE_DATASET_ATTRIBUTE, state.locale);
    document.documentElement.lang = htmlLang(state.locale);
  }, [state.locale]);

  const selectLocale = useCallback((locale: UiLocale) => {
    const next = { locale, source: "explicit" as const };
    setState(next);
    writeStoredLocale(next);
  }, []);

  const adoptDerived = useCallback((locale: UiLocale) => {
    setState((current) => {
      if (current.source === "explicit" || current.locale === locale) return current;
      const next = { locale, source: "derived" as const };
      writeStoredLocale(next);
      return next;
    });
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({ locale: state.locale, source: state.source, selectLocale, adoptDerived }),
    [state.locale, state.source, selectLocale, adoptDerived],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}

/** 取词：返回整棵字典，按命名空间属性访问（拼错 key 即编译期失败）。 */
export function useT(): Dictionary {
  return DICTIONARIES[useContext(LocaleContext).locale];
}
