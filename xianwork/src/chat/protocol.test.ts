import { describe, expect, it } from "vitest";

import {
  historyToTimeline,
  toDisplayUrl,
  type TimelineItem,
} from "./protocol";

type UserItem = Extract<TimelineItem, { kind: "user" }>;

const asUserItem = (item: TimelineItem) => item as UserItem;

describe("toDisplayUrl", () => {
  it("复用 Console 规则把本地文件 URL 转为预览地址", () => {
    expect(
      toDisplayUrl(
        "file:///C:/Users/Administrator/.copaw/workspaces/default/media/image.png",
      ),
    ).toBe(
      "/api/files/preview/C:/Users/Administrator/.copaw/workspaces/default/media/image.png",
    );
  });

  it("保留远程图片地址", () => {
    expect(toDisplayUrl("https://example.com/image.png")).toBe(
      "https://example.com/image.png",
    );
  });

  it("上传存储名（{32hex}_ 前缀）优先走 PG 媒体回显端点", () => {
    expect(
      toDisplayUrl(
        "file:///C:/Users/Administrator/.copaw/workspaces/default/media/8a4c3219aed943bfae3a55ded71f4d89_image.png",
      ),
    ).toBe("/api/console/media/8a4c3219aed943bfae3a55ded71f4d89_image.png");
  });

  it("裸上传存储名也走 PG 媒体回显端点", () => {
    expect(toDisplayUrl("8a4c3219aed943bfae3a55ded71f4d89_image.png")).toBe(
      "/api/console/media/8a4c3219aed943bfae3a55ded71f4d89_image.png",
    );
  });
});

describe("historyToTimeline", () => {
  it("将历史图片转换成与即时消息一致的可展示附件", () => {
    const items = historyToTimeline({
      messages: [
        {
          id: "message-1",
          type: "message",
          role: "user",
          content: [
            { type: "text", text: "分析一下图片内容" },
            {
              type: "image",
              image_url:
                "C:\\Users\\Administrator\\.copaw\\workspaces\\default\\media\\image.png",
            },
          ],
        },
      ],
    });

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "user",
      text: "分析一下图片内容",
      attachments: [
        {
          name: "image.png",
          type: "image/*",
          url: "/api/files/preview/C:\\Users\\Administrator\\.copaw\\workspaces\\default\\media\\image.png",
        },
      ],
    });
  });

  it("将上传媒体持久化的 data 块（source.url）转换成可展示附件", () => {
    const items = historyToTimeline({
      messages: [
        {
          id: "message-2",
          type: "message",
          role: "user",
          content: [
            { type: "text", text: "分析一下当前的国际局势" },
            {
              type: "data",
              source: {
                url: "file:///C:/Users/Administrator/.copaw/workspaces/default/media/0c47e1e4de6e4564ab6bb19ec5432169_cover-horizontal.png",
                type: "url",
                media_type: "image/png",
              },
            },
          ],
        },
      ],
    });

    expect(items).toHaveLength(1);
    expect(asUserItem(items[0]).attachments).toEqual([
      {
        name: "cover-horizontal.png",
        type: "image/png",
        url: "/api/console/media/0c47e1e4de6e4564ab6bb19ec5432169_cover-horizontal.png",
      },
    ]);
  });

  it("data 块缺少 source.url 时不产生附件", () => {
    const items = historyToTimeline({
      messages: [
        {
          id: "message-3",
          type: "message",
          role: "user",
          content: [{ type: "text", text: "纯文本" }],
        },
      ],
    });

    expect(asUserItem(items[0]).attachments).toBeUndefined();
  });
});
