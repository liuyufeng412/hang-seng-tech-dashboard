import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "恒生科技投资工作台",
  description: "恒生科技指数交互式复盘工作台"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
