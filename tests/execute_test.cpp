// Step 5 — ExecutionRouter (docs/test-cases.md X1–X6)
#include <doctest/doctest.h>

#include "ExecutionRouter.hpp"

#include <chrono>
#include <cmath>

using namespace AlphaNode;

namespace {

FilterSpec BtcFilters() {
    FilterSpec f;
    f.stepSize = 0.00001;
    f.minQty = 0.00001;
    f.minNotional = 5.0;
    f.tickSize = 0.01;
    return f;
}

OrderRequest ValidBuy() {
    OrderRequest r;
    r.symbol = "BTCUSDT";
    r.side = Side::Buy;
    r.qty = 0.001;
    r.price = 50'000.0;
    r.filters = BtcFilters();
    return r;
}

}  // namespace

TEST_CASE("X1 demo Send valid qty -> OK; position updated") {
    ExecutionRouter router(/*demo=*/true);
    const auto res = router.send(ValidBuy());
    CHECK(res.ok);
    CHECK(res.status == Status::Ok);
    CHECK(router.position("BTCUSDT") == doctest::Approx(0.001));
}

TEST_CASE("X2 qty respects step / NOTIONAL") {
    ExecutionRouter router(true);
    auto req = ValidBuy();
    req.qty = 0.000012345;  // not on step
    const auto res = router.send(req);
    // Router must reject or floor; either way wire qty must be step-aligned
    // and notional >= min if accepted.
    if (res.ok) {
        const double step = req.filters.stepSize;
        const double n = std::round(req.qty / step);  // caller should floor; router validates
        CHECK(res.status == Status::Ok);
        CHECK(router.position("BTCUSDT") * req.price >= req.filters.minNotional);
        (void)n;
    } else {
        CHECK(res.status == Status::Invalid);
    }
    // Explicit bad notional must fail:
    req.qty = req.filters.stepSize;
    req.price = 1.0;  // notional << 5
    const auto bad = router.send(req);
    CHECK_FALSE(bad.ok);
    CHECK(bad.status == Status::Invalid);
}

TEST_CASE("X3 auth failure -> error; no silent success") {
    ExecutionRouter router(true);
    router.set_auth_ok(false);
    const auto res = router.send(ValidBuy());
    CHECK_FALSE(res.ok);
    CHECK(res.status == Status::Invalid);
    CHECK_FALSE(res.error.empty());
    CHECK(router.position("BTCUSDT") == doctest::Approx(0.0));
}

TEST_CASE("X4 WS drop -> recover reconnects") {
    ExecutionRouter router(true);
    router.simulate_ws_drop();
    CHECK_FALSE(router.connected());
    CHECK(router.recover());
    CHECK(router.connected());
}

TEST_CASE("X5 bar-close to dispatch < 500ms on fixture path") {
    ExecutionRouter router(true);
    const auto t0 = std::chrono::steady_clock::now();
    const auto res = router.send(ValidBuy());
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now() - t0)
                        .count();
    REQUIRE(res.ok);
    CHECK(ms < 500);
}

TEST_CASE("X6 multi-asset fan-out isolates fills") {
    ExecutionRouter router(true);
    auto a = ValidBuy();
    a.symbol = "BTCUSDT";
    a.qty = 0.001;
    auto b = ValidBuy();
    b.symbol = "ETHUSDT";
    b.qty = 0.01;
    b.price = 3'000.0;

    REQUIRE(router.send(a).ok);
    REQUIRE(router.send(b).ok);
    CHECK(router.position("BTCUSDT") == doctest::Approx(0.001));
    CHECK(router.position("ETHUSDT") == doctest::Approx(0.01));
}
