import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quarry — Engineering research, grounded.",
  description:
    "An inspectable workspace for evidence-backed engineering research.",
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
