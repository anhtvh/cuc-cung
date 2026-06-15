// Package vntime provide utility functions working with time in timezone "Asia/Ho_Chi_Minh"
package vntime

import "time"

// Define ...
const (
	YMDLayout  = "2006-01-02"
	YDMLayout  = "2006-02-01"
	MYLayout   = "1/2006"
	MMYYLayout = "01/2006"
	DMYLayout  = "02/01/2006"
	HMSLayout  = "15:04:05"
)

// asiaHoChiMinh present the timezone "Asia/Ho_Chi_Minh", DO NOT change this.
var asiaHoChiMinh = time.FixedZone("Asia/Ho_Chi_Minh", 7*60*60)

// DateTime return time.Date in timezone "Asia/Ho_Chi_Minh"
func DateTime(year, month, day, hour, min, sec int) time.Time {
	return time.Date(year, time.Month(month), day, hour, min, sec, 0, asiaHoChiMinh)
}

// Date is DateTime without time
func Date(year, month, day int) time.Time {
	return DateTime(year, month, day, 0, 0, 0)
}

// YearMonth is Date with day = 1
func YearMonth(year, month int) time.Time {
	return Date(year, month, 1)
}

// Now return time.Now() in the timezone "Asia/Ho_Chi_Minh"
func Now() time.Time {
	return time.Now().In(asiaHoChiMinh)
}

// Parse is time.ParseInLocation with location = "Asia/Ho_Chi_Minh"
func Parse(layout string, value string) (time.Time, error) {
	return time.ParseInLocation(layout, value, asiaHoChiMinh)
}

// Format formats time parameter into layout input
func Format(t time.Time, layout string) string {
	return t.Format(layout)
}
