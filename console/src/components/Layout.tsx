import { ReactNode } from "react";
import { Link } from "react-router-dom";
import "./Layout.css";

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">
          <h1>WolfPack</h1>
        </div>
        <ul className="nav">
          <li>
            <Link to="/">Review Queue</Link>
          </li>
        </ul>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
