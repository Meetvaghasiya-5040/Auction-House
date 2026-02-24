from django import forms
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
import re


class SetPINForm(forms.Form):
    """Form for setting transaction PIN for the first time"""
    pin = forms.CharField(
        max_length=6,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter 4-6 digit PIN',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]*'
        }),
        label='Transaction PIN'
    )
    confirm_pin = forms.CharField(
        max_length=6,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm PIN',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]*'
        }),
        label='Confirm PIN'
    )
    
    def clean_pin(self):
        """Validate PIN is numeric and 4-6 digits"""
        pin = self.cleaned_data.get('pin')
        if not pin:
            raise ValidationError("PIN is required")
        
        if not re.match(r'^\d{4,6}$', pin):
            raise ValidationError("PIN must be 4-6 digits")
        
        return pin
    
    def clean(self):
        """Validate both PINs match"""
        cleaned_data = super().clean()
        pin = cleaned_data.get('pin')
        confirm_pin = cleaned_data.get('confirm_pin')
        
        if pin and confirm_pin and pin != confirm_pin:
            raise ValidationError("PINs do not match")
        
        return cleaned_data


class VerifyPasswordForm(forms.Form):
    """Form for verifying user's account password before PIN change"""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your account password',
            'autocomplete': 'current-password'
        }),
        label='Account Password'
    )
    
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    
    def clean_password(self):
        """Validate password is correct"""
        password = self.cleaned_data.get('password')
        if not password:
            raise ValidationError("Password is required")
        
        if self.user and not check_password(password, self.user.password):
            raise ValidationError("Incorrect password")
        
        return password


class ChangePINForm(forms.Form):
    """Form for changing transaction PIN (requires 4 digits)"""
    new_pin = forms.CharField(
        max_length=4,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter 4-digit PIN',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'maxlength': '4'
        }),
        label='New Transaction PIN'
    )
    confirm_new_pin = forms.CharField(
        max_length=4,
        min_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm 4-digit PIN',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'maxlength': '4'
        }),
        label='Confirm New PIN'
    )
    
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    
    def clean_new_pin(self):
        """Validate new PIN is exactly 4 digits and not same as old PIN"""
        pin = self.cleaned_data.get('new_pin')
        if not pin:
            raise ValidationError("New PIN is required")
        
        if not re.match(r'^\d{4}$', pin):
            raise ValidationError("PIN must be exactly 4 digits")
        
        # Check if same as old PIN
        if self.user and hasattr(self.user, 'profile') and self.user.profile.transaction_pin:
            if check_password(pin, self.user.profile.transaction_pin):
                raise ValidationError("New PIN cannot be the same as the previous PIN")
        
        return pin
    
    def clean(self):
        """Validate new PINs match"""
        cleaned_data = super().clean()
        new_pin = cleaned_data.get('new_pin')
        confirm_new_pin = cleaned_data.get('confirm_new_pin')
        
        if new_pin and confirm_new_pin and new_pin != confirm_new_pin:
            raise ValidationError("PINs do not match")
        
        return cleaned_data
