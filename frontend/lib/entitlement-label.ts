// ABOUTME: 权益 Profile 的人类可读标签；新增 Profile 后同步 entitlement_profiles.yaml 与界面字典。
// ABOUTME: 未登记的 profile id 原样回显——它是技术标识，不该被翻译成猜测出来的名字。
import type { Dictionary } from "./i18n/dictionary";

export function entitlementLabel(profileId: string, t: Dictionary): string {
  return profileId === "local_single_user@1" ? t.shell.entitlementLocalSingleUser : profileId;
}
