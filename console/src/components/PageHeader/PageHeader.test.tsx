import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "./index";

describe("PageHeader", () => {
  it("renders current breadcrumb", () => {
    render(<PageHeader current="Settings" />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("stops rendering the deprecated parent track", () => {
    render(<PageHeader parent="Home" current="Profile" />);
    expect(screen.getByText("Profile")).toBeInTheDocument();
    // 面包屑已上移到顶部导航条，页内不得出现第二份路径
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
    expect(screen.queryByText("/")).not.toBeInTheDocument();
  });

  it("uses the last items entry as title fallback", () => {
    render(
      <PageHeader items={[{ title: "A" }, { title: "B" }, { title: "C" }]} />,
    );
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.queryByText("A")).not.toBeInTheDocument();
    expect(screen.queryByText("B")).not.toBeInTheDocument();
  });

  it("renders center slot", () => {
    render(<PageHeader center={<span>Center Content</span>} />);
    expect(screen.getByText("Center Content")).toBeInTheDocument();
  });

  it("renders extra slot", () => {
    render(<PageHeader extra={<button>Action</button>} />);
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });

  it("renders afterBreadcrumb slot", () => {
    render(<PageHeader current="Page" afterBreadcrumb={<span>tag</span>} />);
    expect(screen.getByText("tag")).toBeInTheDocument();
  });

  it("renders subRow slot", () => {
    render(<PageHeader subRow={<div>Sub Row Content</div>} />);
    expect(screen.getByText("Sub Row Content")).toBeInTheDocument();
  });

  it("applies className prop", () => {
    const { container } = render(<PageHeader className="custom-class" />);
    expect(container.firstChild).toHaveClass("custom-class");
  });

  it("renders nothing for empty items array", () => {
    const { container } = render(<PageHeader items={[]} />);
    expect(container.querySelector(".breadcrumbSeparator")).toBeNull();
  });

  it("renders no title element content when parent/current are empty", () => {
    const { container } = render(<PageHeader parent="" current="" />);
    expect(container.querySelector(".breadcrumbSeparator")).toBeNull();
    expect(screen.queryByText("/")).not.toBeInTheDocument();
  });
});
