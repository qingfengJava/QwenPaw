import { describe, it, expect, vi, afterEach } from "vitest";
import { adminUsersApi } from "./users";
import { adminGrantsApi } from "./grants";
import { adminQuotasApi } from "./quotas";
import { adminAuditApi } from "./audit";
import { adminKbApi } from "./kb";

// The modules delegate to the shared request() helper; mock it and assert
// on the (path, options) shaping each API produces.
vi.mock("../../request", () => ({
  request: vi.fn((_path: string, _options?: unknown) =>
    Promise.resolve({}),
  ),
}));

import { request } from "../../request";

const mockRequest = vi.mocked(request);

afterEach(() => vi.clearAllMocks());

describe("adminUsersApi", () => {
  it("lists users", async () => {
    await adminUsersApi.list();
    expect(mockRequest).toHaveBeenCalledWith("/admin/users");
  });

  it("creates a user with a JSON body", async () => {
    await adminUsersApi.create({ username: "bob", password: "pw" });
    expect(mockRequest).toHaveBeenCalledWith("/admin/users", {
      method: "POST",
      body: JSON.stringify({ username: "bob", password: "pw" }),
    });
  });

  it("encodes the username in the path", async () => {
    await adminUsersApi.update("a/b@c", { disabled: true });
    expect(mockRequest).toHaveBeenCalledWith(
      `/admin/users/${encodeURIComponent("a/b@c")}`,
      { method: "PATCH", body: JSON.stringify({ disabled: true }) },
    );
  });

  it("grants and revokes roles", async () => {
    await adminUsersApi.grantRole("bob", "team_lead");
    expect(mockRequest).toHaveBeenCalledWith("/admin/users/bob/roles", {
      method: "POST",
      body: JSON.stringify({ role: "team_lead" }),
    });
    await adminUsersApi.revokeRole("bob", "team_lead");
    expect(mockRequest).toHaveBeenCalledWith(
      "/admin/users/bob/roles/team_lead",
      { method: "DELETE" },
    );
  });
});

describe("adminGrantsApi", () => {
  it("keeps slashes inside model keys (path converter)", async () => {
    await adminGrantsApi.putModel("dashscope/qwen-max", {
      roles: ["employee"],
      users: [],
      teams: [],
    });
    expect(mockRequest).toHaveBeenCalledWith(
      "/admin/grants/models/dashscope/qwen-max",
      expect.objectContaining({ method: "PUT" }),
    );
  });

  it("removes an agent grant", async () => {
    await adminGrantsApi.removeAgent("default");
    expect(mockRequest).toHaveBeenCalledWith("/admin/grants/agents/default", {
      method: "DELETE",
    });
  });
});

describe("adminQuotasApi", () => {
  it("encodes the rule key as query params on delete", async () => {
    await adminQuotasApi.remove({
      subject_type: "user",
      subject: "bob",
      model: "*",
      window: "day",
    });
    const [path, options] = mockRequest.mock.calls[0];
    expect(path).toContain("/admin/quotas?");
    expect(path).toContain("subject_type=user");
    expect(path).toContain("subject=bob");
    expect(path).toContain("window=day");
    expect(options).toEqual({ method: "DELETE" });
  });
});

describe("adminAuditApi", () => {
  it("omits empty filters from the query string", async () => {
    await adminAuditApi.query({ agent_id: "default", tool_name: "" });
    const [path] = mockRequest.mock.calls[0];
    expect(path).toBe("/admin/audit?agent_id=default");
  });

  it("passes pagination through", async () => {
    await adminAuditApi.query({ limit: 50, offset: 100 });
    const [path] = mockRequest.mock.calls[0];
    expect(path).toContain("limit=50");
    expect(path).toContain("offset=100");
  });
});

describe("adminKbApi", () => {
  it("creates a kb with scope + grants", async () => {
    await adminKbApi.create({
      name: "runbook",
      scope: "team",
      team_id: "core",
      grants_roles: ["team_lead"],
    });
    expect(mockRequest).toHaveBeenCalledWith("/admin/kb", {
      method: "POST",
      body: JSON.stringify({
        name: "runbook",
        scope: "team",
        team_id: "core",
        grants_roles: ["team_lead"],
      }),
    });
  });

  it("ingests text into a kb", async () => {
    await adminKbApi.ingest("kb_1", { text: "hello", title: "doc" });
    expect(mockRequest).toHaveBeenCalledWith("/admin/kb/kb_1/documents", {
      method: "POST",
      body: JSON.stringify({ text: "hello", title: "doc" }),
    });
  });
});
