package kr.kimbiseo.phone.gh

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 김비서 GH 순수 규칙 — 막는 버튼(4언어+영어)·비밀 칸·걸음 상한·문장 해석·두뇌 JSON. */
class GhRulesTest {
    // ---------------------------------------------------------------- 안전: 막는 버튼
    @Test fun blocks_payment_buttons_in_all_languages() {
        val ko = listOf("결제", "결제하기", "주문하기", "주문 확인", "구매하기", "바로구매", "송금", "이체")
        val en = listOf("Pay", "Payment", "Checkout", "Check out", "Place order", "Order now", "Buy now", "Confirm order")
        val ja = listOf("支払い", "決済", "注文する", "購入", "レジ")
        val zh = listOf("支付", "付款", "结算", "下单", "购买", "立即购买", "去结算")
        for (s in ko + en + ja + zh) assertNotNull("막아야 함: $s", GhSafety.blockedTap(s))
    }

    @Test fun allows_cart_and_normal_buttons() {
        for (s in listOf("장바구니 담기", "장바구니에 담기", "Add to cart", "カートに入れる", "加入购物车", "검색", "더보기")) {
            assertNull("막으면 안 됨: $s", GhSafety.blockedTap(s))
        }
    }

    @Test fun secret_fields() {
        for (s in listOf("비밀번호", "카드번호", "Password", "Card number", "CVV", "パスワード", "カード番号", "密码", "卡号"))
            assertTrue("비밀 칸: $s", GhSafety.secretField(s))
        for (s in listOf("검색어", "상품명", "이름", "Search")) assertFalse(GhSafety.secretField(s))
    }

    @Test fun step_limit_is_fifteen() {
        assertTrue(GhSafety.stepAllowed(1))
        assertTrue(GhSafety.stepAllowed(15))
        assertFalse(GhSafety.stepAllowed(16))
        assertFalse(GhSafety.stepAllowed(0))
        assertEquals(15, GhSafety.MAX_STEPS)
    }

    @Test fun target_apps_only() {
        for (p in listOf("com.coupang.mobile", "com.coupang.eats", "com.sampleapp", "com.android.chrome", "com.nhn.android.search"))
            assertTrue(GhSafety.targetOk(p))
        for (p in listOf("com.android.settings", "com.google.android.youtube", "kr.kimbiseo.phone.gh", ""))
            assertFalse(GhSafety.targetOk(p))
        assertTrue(GhSafety.delivery("com.coupang.eats"))
        assertTrue(GhSafety.delivery("com.sampleapp"))
        assertFalse(GhSafety.delivery("com.coupang.mobile"))
    }

    @Test fun cart_confirmation_in_all_languages() {
        assertTrue(GhSafety.cartAdded(listOf("장바구니에 담았습니다")))
        assertTrue(GhSafety.cartAdded(listOf("Added to cart")))
        assertTrue(GhSafety.cartAdded(listOf("カートに追加しました")))
        assertTrue(GhSafety.cartAdded(listOf("已加入购物车")))
        assertFalse(GhSafety.cartAdded(listOf("장바구니에 담기", "검색 결과")))
    }

    // ---------------------------------------------------------------- 문장 해석
    @Test fun phrase_korean() {
        val a = GhPhrase.parse("쿠팡에서 삼다수 2L 장바구니 담아줘")
        assertNotNull(a)
        assertEquals("coupang", a!!.app)
        assertEquals("삼다수 2L", a.query)
    }

    @Test fun phrase_korean_with_particle() {
        val a = GhPhrase.parse("쿠팡에서 삼다수 2L을 장바구니에 담아줘")
        assertNotNull(a)
        assertEquals("삼다수 2L", a!!.query)
    }

    @Test fun phrase_english() {
        val a = GhPhrase.parse("Add Samdasoo 2L to the cart on Coupang")
        assertNotNull(a)
        assertEquals("coupang", a!!.app)
        assertEquals("Samdasoo 2L", a.query)
    }

    @Test fun phrase_japanese() {
        val a = GhPhrase.parse("クーパンで三多水2Lをカートに入れて")
        assertNotNull(a)
        assertEquals("coupang", a!!.app)
        assertEquals("三多水2L", a.query)
    }

    @Test fun phrase_chinese() {
        val a = GhPhrase.parse("在酷澎把三多水2L加入购物车")
        assertNotNull(a)
        assertEquals("coupang", a!!.app)
        assertEquals("三多水2L", a.query)
    }

    @Test fun non_cart_phrase_is_null() {
        assertNull(GhPhrase.parse("쿠팡에서 생수 찾아줘"))
        assertNull(GhPhrase.parse("배민에서 치킨 시켜줘"))
        assertNull(GhPhrase.parse("오늘 날씨 어때"))
        assertNull(GhPhrase.parse("Add water to the cart on YouTube"))   // 대상 아닌 앱
    }

    @Test fun cart_intent_detected() {
        assertTrue(GhPhrase.wantsCart("장바구니에 담아줘"))
        assertTrue(GhPhrase.wantsCart("add to cart"))
        assertFalse(GhPhrase.wantsCart("날씨 검색"))
    }

    // ---------------------------------------------------------------- 두뇌 JSON
    @Test fun brain_reply_variants() {
        assertEquals(GhBrainReply.Decision.Tap(3), GhBrainReply.parse("{\"action\":\"tap\",\"i\":3}"))
        assertEquals(GhBrainReply.Decision.Tap(2), GhBrainReply.parse("{\"tap\":2}"))
        assertEquals(GhBrainReply.Decision.Tap(4), GhBrainReply.parse("{\"i\":4}"))
        assertEquals(GhBrainReply.Decision.Type(1, "삼다수"), GhBrainReply.parse("{\"action\":\"type\",\"i\":1,\"text\":\"삼다수\"}"))
        assertEquals(GhBrainReply.Decision.Back, GhBrainReply.parse("{\"action\":\"back\"}"))
        assertEquals(GhBrainReply.Decision.Wait, GhBrainReply.parse("{\"action\":\"wait\"}"))
        assertTrue(GhBrainReply.parse("{\"done\":true}") is GhBrainReply.Decision.Done)
    }

    @Test fun brain_reply_inside_code_fence_and_prose() {
        assertEquals(GhBrainReply.Decision.Tap(5),
            GhBrainReply.parse("```json\n{\"action\":\"tap\",\"i\":5}\n```"))
        assertEquals(GhBrainReply.Decision.Tap(6),
            GhBrainReply.parse("I think the search box is best. {\"action\":\"tap\",\"i\":6}"))
        assertNull(GhBrainReply.parse("no json here"))
    }

    @Test fun brain_url() {
        assertEquals("http://192.168.0.5:8880/v1/chat/completions", GhBrain.url("http://192.168.0.5:8880/v1/"))
        assertEquals("http://x/v1/chat/completions", GhBrain.url("http://x/v1/chat/completions"))
    }
}