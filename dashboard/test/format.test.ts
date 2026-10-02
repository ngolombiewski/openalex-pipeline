import assert from "node:assert/strict";
import { test } from "node:test";

import { tableRatio } from "../src/format.ts";

test("table ratios round to at most three decimals and trim trailing zeros", () => {
  assert.equal(tableRatio(0.3504), "0.35");
  assert.equal(tableRatio(0.7506), "0.751");
  assert.equal(tableRatio(0.5), "0.5");
  assert.equal(tableRatio(1), "1");
  assert.equal(tableRatio(0), "0");
  assert.equal(tableRatio(0.00049), "0");
});
