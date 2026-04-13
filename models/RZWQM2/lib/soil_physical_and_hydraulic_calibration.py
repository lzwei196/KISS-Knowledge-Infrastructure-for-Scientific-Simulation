class soil_hydraulic_properties_each_horizon:
    def __init__(self,pore_size_dist, saturated_water_content,
                 residual_water_content, bubbling_pressure, constant_for_oh, lateral_ksat, ksat, eps, second_intercept_c2, horizon_num):
        self.bubbling_pressure = bubbling_pressure
        self.pore_size_dist = pore_size_dist
        self.saturated_water_content = saturated_water_content
        self.residual_water_content = residual_water_content
        self.constant_for_oh = constant_for_oh
        self.lateral_ksat = lateral_ksat
        self.ksat = ksat
        self.eps = eps
        self.second_intercept_c2 = second_intercept_c2
        self.horizon_num = horizon_num

    @property
    def fc33(self):
        B1 = (
                         self.saturated_water_content - self.residual_water_content - self.constant_for_oh * self.bubbling_pressure) \
             * self.bubbling_pressure ^ self.pore_size_dist
        fc33 = B1 / (333 ^ self.pore_size_dist) + self.residual_water_content
        return fc33

    @property
    def fc10(self):
        B1 = (
                         self.saturated_water_content - self.residual_water_content - self.constant_for_oh * self.bubbling_pressure) \
             * self.bubbling_pressure ^ self.pore_size_dist
        fc10 = B1 / (100 ^ self.pore_size_dist) + self.residual_water_content
        return fc10

    @property
    def fc15(self):
        B1 = (
                         self.saturated_water_content - self.residual_water_content - self.constant_for_oh * self.bubbling_pressure) \
             * self.bubbling_pressure ^ self.pore_size_dist
        # 15000 is head of wilting point, assuing that 15 bar is the wilting point
        fc15 = B1 / (15000 ^ self.pore_size_dist) + self.residual_water_content
        return fc15
