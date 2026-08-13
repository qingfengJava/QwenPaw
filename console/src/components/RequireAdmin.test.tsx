import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RequireAdmin } from "./RequireAdmin";
import { useAuthStore } from "../stores/authStore";

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={["/admin/users"]}>
      <Routes>
        <Route path="/chat" element={<div>chat page</div>} />
        <Route
          path="/admin/users"
          element={
            <RequireAdmin>
              <div>admin page</div>
            </RequireAdmin>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAdmin (M5 RoleGuard)", () => {
  beforeEach(() => {
    useAuthStore.getState().clear();
  });

  it("renders children for admin identities", () => {
    useAuthStore.getState().setIdentity({
      username: "root",
      role: "admin",
      roles: ["platform_admin"],
    });
    renderGuard();
    expect(screen.getByText("admin page")).toBeInTheDocument();
  });

  it("redirects employees to /chat", () => {
    useAuthStore.getState().setIdentity({
      username: "bob",
      role: "employee",
      roles: ["employee"],
    });
    renderGuard();
    expect(screen.getByText("chat page")).toBeInTheDocument();
    expect(screen.queryByText("admin page")).toBeNull();
  });

  it("redirects anonymous identities", () => {
    renderGuard();
    expect(screen.getByText("chat page")).toBeInTheDocument();
  });
});
