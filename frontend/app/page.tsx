// ABOUTME: 引导页已废止（design.md §3.0）：/ 把用户送回上次编辑的报告，没有则去报告列表；
// ABOUTME: 进度绑定账户不绑定设备——本机指针只是快捷方式，缺失时从服务端事实重建。
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAccount } from "@/lib/account-context";
import { useAuth } from "@/lib/auth-context";
import { currentReportId, setCurrentReportId } from "@/lib/report-store";
import { resolveResumeTarget } from "@/lib/resume-target";

export default function HomeRedirect() {
  const router = useRouter();
  const { loading: authLoading, session, configured } = useAuth();
  const { snapshot, loading: accountLoading } = useAccount();

  useEffect(() => {
    if (authLoading || accountLoading) return;
    // 未配置（本地开发降级）或未登录：交给报告列表页的既有门禁分流。
    if (!configured || !session || !snapshot) {
      router.replace("/reports");
      return;
    }
    const accountId = snapshot.account.id;
    let cancelled = false;

    void (async () => {
      // 本机指针只是同设备内的快捷方式；它缺失（换设备、清缓存、新浏览器）不代表
      // 用户没有进行中的报告。进度属于账户，因此指针缺失时从服务端权威事实重建：
      // 最近编辑的那份活跃报告，以及它当前该继续的那一步。
      const resume = await resolveResumeTarget(currentReportId(accountId));
      if (cancelled) return;
      if (!resume) {
        router.replace("/reports");
        return;
      }
      setCurrentReportId(accountId, resume.reportId);
      router.replace(resume.href);
    })();

    return () => {
      cancelled = true;
    };
  }, [authLoading, accountLoading, configured, session, snapshot, router]);

  return null;
}
