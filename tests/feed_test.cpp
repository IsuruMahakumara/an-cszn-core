// Step 1 — MarketDataFeed (docs/test-cases.md F1–F6)
#include <doctest/doctest.h>

#include "MarketDataFeed.hpp"

#include <cmath>
#include <limits>

using namespace AlphaNode;

namespace {

Bar ValidBar(int64_t t_ms = 1'700'000'000'000) {
    return Bar{100.0, 105.0, 99.0, 103.0, 12.5, t_ms};
}

}  // namespace

TEST_CASE("F1 valid closed bar appended; status Ok") {
    MarketDataFeed feed("BTCUSDT");
    const auto st = feed.ingest(ValidBar());
    CHECK(st == Status::Ok);
    CHECK(feed.history_size() == 1);
}

TEST_CASE("F2 features finite; dim matches model") {
    constexpr std::size_t kDim = 4;
    MarketDataFeed feed("BTCUSDT", kDim);
    REQUIRE(feed.ingest(ValidBar()) == Status::Ok);
    // Need enough history for a rolling window — push a few bars.
    for (int i = 1; i < 8; ++i) {
        REQUIRE(feed.ingest(ValidBar(1'700'000'000'000 + i * 3'600'000)) == Status::Ok);
    }
    const auto fv = feed.features();
    REQUIRE(fv.status == Status::Ok);
    REQUIRE(fv.x.size() == kDim);
    for (double v : fv.x) {
        CHECK(std::isfinite(v));
    }
}

TEST_CASE("F3 zero volume -> Invalid; history unchanged") {
    MarketDataFeed feed("BTCUSDT");
    REQUIRE(feed.ingest(ValidBar()) == Status::Ok);
    const auto before = feed.history_size();
    Bar bad = ValidBar(2);
    bad.volume = 0.0;
    CHECK(feed.ingest(bad) == Status::Invalid);
    CHECK(feed.history_size() == before);
}

TEST_CASE("F4 NaN price -> Invalid; history unchanged") {
    MarketDataFeed feed("BTCUSDT");
    REQUIRE(feed.ingest(ValidBar()) == Status::Ok);
    const auto before = feed.history_size();
    Bar bad = ValidBar(2);
    bad.close = std::numeric_limits<double>::quiet_NaN();
    CHECK(feed.ingest(bad) == Status::Invalid);
    CHECK(feed.history_size() == before);
}

TEST_CASE("F5 gapped bar sequence -> Invalid or gap; engine continues") {
    MarketDataFeed feed("BTCUSDT");
    REQUIRE(feed.ingest(ValidBar(1'000)) == Status::Ok);
    // Skip expected 1h step — large gap.
    const auto st = feed.ingest(ValidBar(1'000 + 10 * 3'600'000));
    CHECK(st == Status::Invalid);
    CHECK_NOTHROW(feed.ingest(ValidBar(1'000 + 11 * 3'600'000)));
}

TEST_CASE("F6 N=1 universe") {
    MarketDataFeed feed("BTCUSDT");
    CHECK(feed.universe_size() == 1);
    CHECK(feed.symbol() == "BTCUSDT");
}
