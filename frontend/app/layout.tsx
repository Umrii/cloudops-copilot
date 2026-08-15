import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CloudOps Copilot",
  description:
    "An evaluated RAG assistant for troubleshooting Google Cloud, grounded in Google Cloud documentation.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
