import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 生产环境只上传运行时追踪到的依赖；静态资源由本机构建脚本一并复制。
  output: "standalone",
  // dev server 以默认 hostname（localhost）启动时，Next 会拦截来自其他 origin 的 dev 资源请求；
  // 放行 127.0.0.1，使 Playwright 默认 baseURL（127.0.0.1:3000）可复用手动起的 localhost dev server。
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
