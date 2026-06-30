#include <gtest/gtest.h>
#include <cstring>
#include "../HotPathParser.hpp"
#include "../L2BookStruct.hpp"

using namespace HotPath;

TEST(ParserTest, ValidPolymarketL2) {
    L2BookStruct book;
    std::memset(&book, 0, sizeof(L2BookStruct));
    
    std::string_view json = "{\"event_type\":\"order_book\",\"bids\":[[\"0.552\",\"100\"]],\"asks\":[[\"0.561\",\"100\"]]}";
    
    bool success = PolymarketParser::ParseL2(json, &book);
    
    EXPECT_TRUE(success);
    EXPECT_DOUBLE_EQ(book.poly_up_bids[0].price, 0.552);
    EXPECT_DOUBLE_EQ(book.poly_up_asks[0].price, 0.561);
}

TEST(ParserTest, MalformedJSON) {
    L2BookStruct book;
    std::string_view json = "{\"invalid\": true}";
    
    bool success = PolymarketParser::ParseL2(json, &book);
    EXPECT_FALSE(success);
}

TEST(ParserTest, FragmentedJSON) {
    L2BookStruct book;
    std::string_view json = "{\"event_type\":\"order_book\",\"bids\":[[\"0.55";
    
    bool success = PolymarketParser::ParseL2(json, &book);
    EXPECT_FALSE(success);
}

TEST(ParserTest, EmptyJSON) {
    L2BookStruct book;
    bool success = PolymarketParser::ParseL2("", &book);
    EXPECT_FALSE(success);
}

TEST(ParserTest, NumericPrecision) {
    L2BookStruct book;
    std::memset(&book, 0, sizeof(L2BookStruct));
    std::string_view json = "{\"event_type\":\"order_book\",\"bids\":[[\"0.12345678\",\"1\"]],\"asks\":[[\"0.98765432\",\"1\"]]}";
    
    bool success = PolymarketParser::ParseL2(json, &book);
    
    EXPECT_TRUE(success);
    EXPECT_NEAR(book.poly_up_bids[0].price, 0.12345678, 1e-9);
    EXPECT_NEAR(book.poly_up_asks[0].price, 0.98765432, 1e-9);
}
