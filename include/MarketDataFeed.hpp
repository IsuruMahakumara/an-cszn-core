#pragma once

#include "Types.hpp"

#include <limits>
#include <string>
#include <vector>

namespace AlphaNode {

// TDD stub — implement until feed_test.cpp is green.
class MarketDataFeed {
public:
    explicit MarketDataFeed(std::string symbol, std::size_t feature_dim = 4)
        : symbol_(std::move(symbol)), feature_dim_(feature_dim) {}

    Status ingest(const Bar& bar) {
        (void)bar;
        // Red: always Invalid until implemented.
        return Status::Invalid;
    }

    std::size_t history_size() const { return history_.size(); }

    FeatureVector features() const {
        FeatureVector out;
        out.status = Status::Invalid;
        out.x.assign(feature_dim_, std::numeric_limits<double>::quiet_NaN());
        return out;
    }

    const std::string& symbol() const { return symbol_; }
    std::size_t universe_size() const { return 1; }
    std::size_t feature_dim() const { return feature_dim_; }

private:
    std::string symbol_;
    std::size_t feature_dim_;
    std::vector<Bar> history_;
};

}  // namespace AlphaNode
