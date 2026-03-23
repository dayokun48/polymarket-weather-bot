"""
Weather Arbitrage Analyzer
Finds opportunities by comparing NOAA vs Polymarket
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class WeatherAnalyzer:
    """
    Analyzes weather forecasts vs market odds
    Finds arbitrage opportunities
    """
    
    def __init__(self, noaa_collector, polymarket_collector):
        self.noaa = noaa_collector
        self.polymarket = polymarket_collector
    
    def find_opportunities(self, location: str) -> List[Dict]:
        """
        Find arbitrage opportunities for location
        
        Returns list of signals
        """
        signals = []
        
        try:
            # Get NOAA forecast
            forecast = self.noaa.get_forecast(location)
            if not forecast:
                logger.warning(f"No forecast available for {location}")
                return []
            
            # Get Polymarket markets
            markets = self.polymarket.search_weather_markets(location)
            if not markets:
                logger.info(f"No weather markets found for {location}")
                return []
            
            logger.info(f"Analyzing {len(markets)} markets for {location}")
            
            # Compare each market with forecast
            for market in markets:
                signal = self._analyze_market(market, forecast)
                
                if signal:
                    signals.append(signal)
            
            return signals
            
        except Exception as e:
            logger.error(f"Error analyzing {location}: {e}")
            return []
    
    def _analyze_market(self, market: Dict, forecast: Dict) -> Optional[Dict]:
        """
        Analyze single market vs forecast
        
        Returns signal if arbitrage found, else None
        """
        try:
            # Extract location from market question
            location = self.polymarket.extract_location_from_question(
                market['question']
            )
            
            # Extract target date
            target_date = self.polymarket.extract_date_from_question(
                market['question']
            )
            
            if not target_date:
                # Try to use market end date
                if market['end_date']:
                    target_date = market['end_date'].strftime('%Y-%m-%d')
                else:
                    return None
            
            # Find matching forecast
            matching_forecast = None
            for period in forecast['forecasts']:
                if period['date'] == target_date:
                    matching_forecast = period
                    break
            
            if not matching_forecast:
                return None
            
            # Check if it's a rain market
            question_lower = market['question'].lower()
            is_rain_market = 'rain' in question_lower or 'precipitation' in question_lower
            
            if not is_rain_market:
                return None  # Only handle rain markets for now
            
            # Get NOAA probability
            noaa_prob = matching_forecast['rain_probability'] / 100  # Convert to 0-1
            
            # Get market probability
            market_prob = market['yes_price']
            
            # Calculate edge
            edge = abs(noaa_prob - market_prob)
            edge_percent = edge * 100
            
            # Determine direction
            if noaa_prob > market_prob:
                direction = 'YES'
                recommended_prob = noaa_prob
                fair_value = noaa_prob
            else:
                direction = 'NO'
                recommended_prob = 1 - noaa_prob
                fair_value = 1 - noaa_prob
            
            # Calculate expected value
            if direction == 'YES':
                payout_multiplier = 1 / market['yes_price'] if market['yes_price'] > 0 else 2
                expected_value = (noaa_prob * payout_multiplier) - 1
            else:
                payout_multiplier = 1 / market['no_price'] if market['no_price'] > 0 else 2
                expected_value = ((1 - noaa_prob) * payout_multiplier) - 1
            
            # Calculate confidence
            confidence = self._calculate_confidence(
                edge_percent,
                matching_forecast,
                market
            )
            
            # Only return if edge is significant
            if edge_percent < 10:  # Min 10% edge
                return None
            
            return {
                'market_id': market['id'],
                'market_question': market['question'],
                'market_url': market['url'],
                'location': location or forecast['location'],
                'target_date': target_date,
                'signal_type': 'weather_rain',
                'direction': direction,
                'noaa_probability': noaa_prob * 100,
                'market_probability': market_prob * 100,
                'edge': edge_percent,
                'confidence': confidence,
                'fair_value': fair_value,
                'current_price': market_prob if direction == 'YES' else market['no_price'],
                'expected_value': expected_value * 100,
                'recommended_bet': 0,  # Will be calculated by risk manager
                'reasoning': self._generate_reasoning(
                    noaa_prob, market_prob, matching_forecast, direction
                ),
                'market_volume': market['volume'],
                'market_liquidity': market['liquidity'],
                'market_end_date': market['end_date'],
                'forecast_conditions': matching_forecast['conditions'],
                'created_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error analyzing market {market.get('id')}: {e}")
            return None
    
    def _calculate_confidence(self, edge: float, forecast: Dict, market: Dict) -> float:
        """
        Calculate confidence score (0-100)
        
        Based on:
        - Edge size
        - Forecast certainty
        - Market liquidity
        - Time to event
        """
        confidence = 50  # Base
        
        # Edge contribution (max +30)
        if edge > 30:
            confidence += 30
        elif edge > 20:
            confidence += 20
        elif edge > 10:
            confidence += 10
        
        # Forecast certainty (max +20)
        rain_prob = forecast['rain_probability']
        if rain_prob > 80 or rain_prob < 20:
            confidence += 20  # Very certain
        elif rain_prob > 70 or rain_prob < 30:
            confidence += 10  # Fairly certain
        
        # Market liquidity (max +10)
        if market['liquidity'] > 10000:
            confidence += 10
        elif market['liquidity'] > 5000:
            confidence += 5
        
        return min(confidence, 95)  # Cap at 95%
    
    def _generate_reasoning(self, noaa_prob: float, market_prob: float,
                           forecast: Dict, direction: str) -> str:
        """Generate human-readable reasoning"""
        
        noaa_pct = noaa_prob * 100
        market_pct = market_prob * 100
        edge = abs(noaa_pct - market_pct)
        
        reasoning = f"NOAA forecasts {noaa_pct:.0f}% rain probability "
        reasoning += f"while Polymarket prices {market_pct:.0f}%. "
        reasoning += f"Edge: {edge:.0f}%. "
        reasoning += f"Forecast: {forecast['conditions']}. "
        
        if direction == 'YES':
            reasoning += "Market significantly underpricing rain probability."
        else:
            reasoning += "Market significantly overpricing rain probability."
        
        return reasoning
