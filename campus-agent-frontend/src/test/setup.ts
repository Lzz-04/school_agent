// vitest 全局初始化：jest-dom 匹配器 + 每用例后自动清理 DOM
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom 未实现 Element.scrollTo（Chat 组件挂载时会调用），补空实现
if (typeof Element !== "undefined" && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}

afterEach(() => cleanup());
