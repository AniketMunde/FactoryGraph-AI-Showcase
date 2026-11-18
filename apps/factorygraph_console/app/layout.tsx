import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "FactoryGraph AI | Operations Console",
  description: "Authenticated historical machine investigation with source-grounded evidence.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
