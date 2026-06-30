#include <gtest/gtest.h>
#include "../AccountStateStruct.hpp"
#include <cstring>

TEST(AccountTest, StructLayout) {
    AccountStateStruct acc;
    std::memset(&acc, 0, sizeof(AccountStateStruct));
    
    acc.sequence.store(10);
    acc.available_collateral = 10000.0;
    acc.total_equity = 15000.0;
    acc.total_maint_margin = 2000.0;
    acc.next_nonce.store(1001);
    acc.last_update_ts = 1700000000;
    
    EXPECT_EQ(sizeof(AccountStateStruct), 64);
    EXPECT_EQ(acc.sequence.load(), 10);
    EXPECT_DOUBLE_EQ(acc.available_collateral, 10000.0);
    EXPECT_DOUBLE_EQ(acc.total_equity, 15000.0);
    EXPECT_DOUBLE_EQ(acc.total_maint_margin, 2000.0);
    EXPECT_EQ(acc.next_nonce.load(), 1001);
    EXPECT_EQ(acc.last_update_ts, 1700000000);
}

TEST(AccountTest, PaddingVerification) {
    // Ensure padding doesn't affect data integrity on 64-bit systems
    EXPECT_EQ(offsetof(AccountStateStruct, available_collateral), 8);
    EXPECT_EQ(offsetof(AccountStateStruct, total_equity), 16);
    EXPECT_EQ(offsetof(AccountStateStruct, total_maint_margin), 24);
    EXPECT_EQ(offsetof(AccountStateStruct, up_position), 32);
    EXPECT_EQ(offsetof(AccountStateStruct, down_position), 40);
    EXPECT_EQ(offsetof(AccountStateStruct, next_nonce), 48);
    EXPECT_EQ(offsetof(AccountStateStruct, last_update_ts), 56);
}
