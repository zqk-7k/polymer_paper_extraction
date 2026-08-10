import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PolymerLit Extractor | 高分子文献抽取工具",
  description: "上传高分子论文，跟踪抽取 Stage，并审核聚合物、样品、性质与原文证据。",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
