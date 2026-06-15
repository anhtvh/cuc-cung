package constant

type ServiceID string

const (
	ServiceIDElectric   ServiceID = "DIEN"
	ServiceIDWater      ServiceID = "NUOC"
	ServiceIDInternet   ServiceID = "NET"
	ServiceIDTelevision ServiceID = "CAP"
	ServiceIDEducation  ServiceID = "EDUCATION"
	ServiceIDTTD        ServiceID = "TTD"
	ServiceIDTTTG       ServiceID = "TTTG"
	ServiceIDApartment  ServiceID = "APARTMENTFEE"
	ServiceIDEVN        ServiceID = "EVN"
)

const (
	BillDebt    = 1
	BillService = 6

	TypeDebt = "DEBT_COLLECTION"

	PrefixThanhHoa = "PA07"
	PrefixHaiDuong = "PM"
	PrefixDienBien = "PA19"
)
